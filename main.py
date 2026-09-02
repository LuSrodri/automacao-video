"""Automação de vídeos de análise sobre o que está acontecendo, a partir das
trends do X.

SEM RECORTE TEMÁTICO (2026-08-16, pedido do usuário): qualquer assunto pode
virar vídeo — tecnologia, IA, negócios, trabalho, mercado, ciência, saúde,
política, mundo, esporte, cultura, crime, clima, consumo. Não há tema vetado
nem tema obrigatório; o que decide a pauta é o valor da informação e, entre as
candidatas, o que a audiência do canal assiste até o fim.

Fluxo:
1. X API coleta os posts que viram pauta, de DUAS FONTES em ordem (2026-08-28):
   as X_MAX_POSTS CURTIDAS MAIS RECENTES do usuário, sem recorte de data
   (`/2/users/:id/liked_tweets`; a janela de dias saiu em 2026-08-29) e, em
   QUALQUER erro ou filtro delas, a LISTA DO X (X_LIST_ID,
   `/2/lists/{id}/tweets`) — erro de leitura, menos de X_CURTIDOS_MIN posts
   aproveitáveis, ou (desde 2026-08-29) a auditoria reprovando o material de
   todas as candidatas lá no passo 7, que é quando o laço de fallback lê a
   lista e recomeça em vez de abortar. Curtir um
   post no X é a forma mais barata de mexer na pauta; pôr ou tirar alguém da
   lista continua sendo a segunda. Só sobe post com clipe de vídeo nativo, e só
   clipe dentro da FAIXA DE DURAÇÃO do formato (`config.faixa_de_clipe`): 15 a
   30s no Short, 30 a 90s no longo. O GPT sumariza os posts
   nas 10 trends mais quentes, ordenadas pelo VALOR DA INFORMAÇÃO (vazamento,
   exclusivo, urgência, número inédito) antes do engajamento. Falhar nas DUAS
   fontes aborta a execução, em vez de deixar o vídeo sair de uma pauta pior
   sem ninguém ver.
2. GPT classifica cada candidata (macrotema + imagem mental). Desde 2026-08-28
   a candidata do balde "outro" — a que não coube em nenhum macrotema
   definido — sai da disputa; as demais seguem vivas para a seleção, sem score
   nem peso.
3. GPT escolhe a trend: primeiro corte pelo VALOR DA INFORMAÇÃO (vazamento,
   exclusivo, urgência, número inédito), e entre as elegíveis decide pela
   audiência — recebe os últimos vídeos publicados do canal com as métricas
   reais (views/likes, YouTube Data API) e a RÉGUA DE RETENÇÃO (YouTube
   Analytics). No SHORT a régua é ESTRITA (2026-08-22, os dois canais): entram
   os vídeos que passam AO MESMO TEMPO em engajamento > ENGAJAMENTO_MINIMO% e
   views acima do piso, limitados aos LIMITE_REFERENCIA melhores — e o único
   afrouxamento possível é baixar o piso de views de PASSO_FALLBACK_VIEWS em
   PASSO_FALLBACK_VIEWS até a lista sair do vazio. A RETENÇÃO saiu da régua do
   Short em 2026-08-22 (irrelevante para este canal, conferido no Studio).
   Cada campeão do Short ainda recebe um DOSSIÊ (pipeline/referencia.py):
   descrição publicada, a legenda do próprio vídeo e a leitura da capa, tudo
   montado em memória e descartado no fim da execução. No formato LONGO vale a
   régua anterior — retenção, teto e piso de engajamento que cede quando
   esvazia a lista. Regra dura: a escolhida passa por uma verificação anti-repetição
   (GPT confere se ela cobriria o mesmo fato de um vídeo publicado nas últimas
   36h; se sim, sai da disputa e a seleção refaz). Define também uma consulta
   curta do assunto (busca de clipes) e uma consulta de busca do YouTube.
4. PANORAMA DO DIA (SEO/GEO, pipeline/seo.py): a YouTube Data API devolve os
   vídeos que OUTROS canais publicaram sobre o mesmo assunto nas últimas
   JANELA_HORAS, com views/hora e o vocabulário de tags deles. É a única
   leitura do pipeline sobre a disputa FORA do canal, e alimenta título,
   descrição, tags e capa. Falha aqui só avisa (SEO_PANORAMA=0 desliga).
   A busca de NOTÍCIAS no Firecrawl que existia aqui foi REMOVIDA em
   2026-08-16: os fatos vêm só dos posts do X, e o pipeline não tem mais
   dependência nenhuma do Firecrawl.
5. GPT escreve o roteiro explicativo (análise/educacional) em tom adulto,
   citando as fontes (as contas do X que trouxeram o fato, e o veículo que elas
   citam). No SHORT a estrutura é CONTEXTUALIZAÇÃO -> FATO, e o vídeo acaba em
   CORTE SECO no último detalhe factual: nada de conclusão, consequência ou
   frase de encerramento (2026-09-02). O que emenda no reinício do Short (loop)
   passou a ser o próprio corte no meio do assunto, e não mais uma conclusão
   fechando na promessa da abertura — o preview e a consequência saíram do
   esquema junto com os blocos. A pergunta esquisita saiu da narração em
   2026-08-25; ela sobrou como campo, só para o par P:/R: da descrição. O
   formato LONGO mantém a estrutura dele (pauta falada, tópicos e fecho).
6. X API baixa um POOL de clipes de vídeo dos posts originais da trend (mais
   do que os 3 que entram na montagem, como folga para a auditoria), junto das
   fotos dos posts, que alimentam as cartelas. Imagem estática nunca ocupa a
   tela; trend sem post com vídeo nem chega aqui — a seleção já a descarta.
7. AUDITORIA do material visual: o GPT (visão) descreve e CLASSIFICA cada
   clipe, o veto duro derruba material de telejornal e imagem com selo de
   emissora, e uma nota de pertinência (1-5) derruba o clipe que não mostra o
   que a narração diz. No formato longo o telejornal não é vetado: entra
   MARCADO como representação visual (dessaturado + etiqueta na tela). O veto
   por TEXTO NA TELA entra aqui também: clipe tomado por texto — e, mais
   ainda, por texto PARADO — sai, a não ser que aquele texto seja o assunto
   que a narração descreve (o post citado, a tela do produto, o número
   falado); o clipe fica embaixo das legendas queimadas, e texto sobre texto
   não é lido por ninguém (VETO_TEXTO_DENSO=0 desliga). Roda antes do TTS para
   a reprovação não custar créditos.
   FALLBACK DE TEMA: ficar abaixo do piso de clipes aprovados (1 no curto,
   LONGO_MIN_CLIPES_APROVADOS no longo) — ou não conseguir baixar clipe
   nenhum — não aborta mais a execução: a candidata sai da disputa e os passos
   4 a 7 refazem com a próxima trend, até TENTATIVAS_TREND candidatas. E
   esgotadas as TENTATIVAS_TREND candidatas das CURTIDAS, o laço lê a LISTA do
   X e recomeça com a pauta dela (2026-08-29) — só depois de as duas fontes
   falharem é que a execução aborta.
8. ElevenLabs narra o texto (TTS), o pipeline acelera a narração conforme o
   formato (o Short é acelerado, o longo roda em velocidade normal) e corta os
   silêncios; os timestamps do alinhamento acompanham as duas coisas.
9. A IA planeja os cortes: um "editor de cortes" casa cada clipe aprovado com
   o momento exato da narração (citações do texto -> timestamps do
   alinhamento).
10. Cartelas de imagem nos momentos-chave (SÓ NO SHORT desde 2026-08-25): foto
    do post da trend, auditada igual aos clipes, tomando a TELA INTEIRA quando a
    narração nomeia o que ela mostra.
11. Daqui em diante os DOIS FORMATOS SE SEPARAM (2026-08-25). O FORMATO LONGO
    passou a ser montado em PARTES separadas, coladas no ffmpeg — ver o
    bloco do formato longo mais abaixo e pipeline/montagem_longa.py. O que segue
    nos itens 12 e 13 é o caminho do SHORT.
12. ffmpeg monta o vídeo em TELA CHEIA (2026-08-16, pedido do usuário): o
    conteúdo ocupa o QUADRO INTEIRO, com o preenchimento de fundo em desfoque
    do próprio clipe. Saíram os cenários que embrulhavam o vídeo — a moldura de
    celular sobre uma cama e, antes dela, a sala com TV —, e com eles o módulo
    cenario.py e a foto fundo-cama.png. Fundo = o próprio clipe borrado
    (cobertura total, sem instante vazio) + clipe nítido centrado + crossfade
    curto + legendas grandes (Archivo Black, altura levemente reduzida) +
    crédito de reprodução no canto superior direito ("Reprodução Imagem: X" +
    conta do post). As cartelas entram por um CARROSSEL de duas
    posições: o conteúdo desliza para a esquerda e a imagem ocupa a tela; no
    fim da janela ela desliza de volta e o vídeo retorna. SEM música de fundo.
13. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
    YouTube (o horário de publicação é o do cronjob que dispara a execução)
    com TAGS de busca (que iam vazias até 2026-08-07) e com a descrição
    montada em pipeline/seo.py: parágrafo do payload, par P:/R: (a parte de
    GEO — a frase autossuficiente que um buscador com IA consegue citar),
    capítulos no formato longo, fontes reais e as hashtags por último. O
    YouTube é o ÚNICO destino: a publicação secundária no TikTok (via Zernio)
    foi removida em 2026-08-16 a pedido do usuário — não reintroduzir sem
    pedido explícito.

Formatos (o mesmo fluxo acima, com parâmetros diferentes):
- padrão: Short vertical 1080x1920 de ATÉ ~25s (era 60 até 2026-08-09), com
  legendas queimadas e narração a 1,05x (VIDEO_VELOCIDADE; era 1,25x até
  2026-09-01). Os Shorts INTERCALAM temas — o macrotema do Short anterior sai
  da disputa da seleção.
  O MATERIAL DIMENSIONA O ROTEIRO desde 2026-08-28 (pedido do usuário): o
  Short não repete mais clipe em loop, então os ~25s viraram um TETO e não uma
  meta — o roteiro é escrito para os segundos de clipe que a pauta tem
  (`alvo_pelo_material`, config.py), a auditoria confere se o material aprovado
  cobre a narração e a montagem encaixa as janelas no que existe
  (`_encaixar_no_material`, edicao.py). O ZOOM INTELIGENTE que transforma clipe
  horizontal em vertical (enquadramento.py) continua valendo.
  A DURAÇÃO FECHA EM TRÊS CAMADAS, nesta ordem: o orçamento de PALAVRAS
  (escritor, até 5 reescritas), a VELOCIDADE da narração depois de medir o
  áudio (audio.ajustar_ao_alvo, presa entre 1,00x e 1,15x) e, se a faixa de
  velocidade não fechar, a REESCRITA DO TEXTO pelo ritmo medido, com uma
  segunda narração (TENTATIVAS_NARRACAO).
- `--long-take`: vídeo de ANÁLISE em 16:9 (1920x1080), com TETO de
  LONG_DURACAO (máximo LONGO_MAX_S=150s) e sem piso, SEM legendas e em
  velocidade NORMAL, para os dois canais (combina com `-usa`). O roteiro
  explica os acontecimentos do dia cobrindo EXATAMENTE 4 PAUTAS
  (LONGO_NUM_TRENDS; eram 3 até 2026-09-02) — uma trend por pauta, cada uma com
  o seu clipe, ou recortes diferentes do mesmo fato quando o material só traz
  um (quem fez, quem paga, quem ganha, quem perde, o que vem depois).

  O MATERIAL DIMENSIONA O LONGO TAMBÉM, e por CAPÍTULO (2026-09-01, pedido do
  usuário: "sempre priorizar o tamanho do material" e "para evitar o loop no
  vídeo longo, pode ser flexível a duração de cada capítulo"). Cada uma das
  pautas dura o que o clipe DELA dá (`alvos_das_pautas`, config.py), a
  abertura fica com ~LONGO_ABERTURA_S, e a soma é a duração do vídeo. Como
  cada pauta recebe UM clipe e nenhum serve a duas, é essa conta que tira o
  loop do formato — o `-stream_loop` da montagem virou rede contra tela preta,
  não mais o mecanismo que enchia a parte. Consequência esperada: os vídeos
  longos passam a variar de tamanho. Desde 2026-09-02 o clipe do longo é
  obrigado a ter 30 a 90s, então a variação passou a ser para CIMA: quatro
  pautas de clipe no piso já somam ~116s, e material acima disso é encolhido
  proporcionalmente para caber no teto de LONG_DURACAO.

  NÃO HÁ MAIS PISO DE DURAÇÃO EM NENHUM FORMATO (2026-09-01, pedido do
  usuário: "pode tirar qualquer piso que tiver"). Saíram, juntos: o piso de
  trecho útil do clipe (PISO_DUR_UTIL_S, 5s, que era o piso EFETIVO do Short
  desde 28/08), o piso de duração do longo (LONGO_MIN_S, 120s) e o piso de
  cada capítulo do longo (LONGO_PAUTA_MIN_S, 20s). Os TETOS ficam — inclusive
  o da abertura do longo (LONGO_ABERTURA_MAX_S), que é sincronia de painel e
  não ritmo. Continuam valendo, e não são pisos de tempo: o mínimo de clipes
  APROVADOS (1 no curto, 3 no longo — aritmética da montagem) e a nota de
  PERTINÊNCIA do clipe.

  O PISO SAIU DO VÍDEO, NÃO DO MATERIAL. Em 2026-09-02 entrou uma FAIXA DE
  DURAÇÃO DO CLIPE por formato (15-30s no Short, 30-90s no longo), a pedido do
  usuário. Ela age na COLETA, sobre o insumo, e não sobre o produto: não há
  vídeo abortado por ser curto — há material que não entra por não ter o
  tamanho que o formato usa. O efeito prático é que o vídeo herda o piso do
  material que sobrou.

  A MONTAGEM EM PARTES (2026-08-25, desenho do usuário) é o que define
  este formato. O vídeo NÃO é um bloco corrido com sobreposições ligando e
  desligando: são a abertura mais uma parte por pauta, cada uma renderizada
  sozinha e coladas no ffmpeg (pipeline/montagem_longa.py).

      +--------------+ +--------+ +--------+ +--------+ +--------+
      |   4 clipes   | |clipe 1 | |clipe 2 | |clipe 3 | |clipe 4 |
      | [AINDA NESTE | |[MANCHE-| |[MANCHE-| |[MANCHE-| |[MANCHE-|
      |    VÍDEO]    | | TE 1]  | | TE 2]  | | TE 3]  | | TE 4]  |
      +--------------+ +--------+ +--------+ +--------+ +--------+
           ~12s       ^          ^         ^          ^      fade
                    pausa      pausa     pausa      pausa   out 3s
                    0,7s       0,7s      0,7s       0,7s

  As regras que a estrutura torna DURAS, e que antes eram só preferências de
  prompt:
    - O PAINEL DE TEXTO NUNCA SAI DA TELA. Cada parte tem o seu do primeiro ao
      último quadro; a troca acontece dentro da pausa de silêncio da virada, o
      painel velho saindo pela esquerda e o novo entrando. Uma troca por pauta
      a partir da segunda. Antes a manchete durava 4,2s e sumia.
    - CADA PAUTA TEM O SEU CLIPE, e um clipe não serve a duas. Quem casa clipe
      e pauta é `cortes.atribuir_clipes`, e a montagem ABORTA se um repetir.
      A abertura mostra todos em sequência — é a prévia do que foi prometido.
    - As CITAÇÕES de virada são conferidas ANTES da narração
      (escritor._conferir_estrutura_longa): sem elas não há onde cortar.
  Usa até 10 clipes do X (4 entram na montagem), NÃO usa cartelas, e a
  descrição sai com a lista de fontes reais.

Idioma: o canal decide, nunca o modelo. Canal brasileiro publica TUDO em
português (título, descrição, narração, capa); canal americano (`-usa`), TUDO
em inglês.
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from pipeline.audio import ajustar_ao_alvo, gerar_narracao
from pipeline.auditoria import auditar_midias
from pipeline.cartelas import gerar_cartelas
from pipeline.classificacao import classificar_trends, filtrar_por_macrotema
from pipeline.config import (
    CURTO_VELOCIDADE_MAX,
    CURTO_VELOCIDADE_MIN,
    LONGO_MAX_S,
    LONGO_MIN_CLIPES_APROVADOS,
    LONGO_NUM_TRENDS,
    MATERIAL_MARGEM,
    TENTATIVAS_NARRACAO,
    TENTATIVAS_TREND,
    alvo_pelo_material,
    alvos_das_pautas,
    ativar_formato_longo,
    carregar_config,
    segundos_uteis,
)
from pipeline.apuracao import apurar
from pipeline.cortes import atribuir_clipes, planejar_cortes, texto_da_pauta
from pipeline.edicao import (
    RESPIRO_FINAL,
    duracao_audio,
    intervalos_imagens,
    marcar_memoria,
    montar_video,
)
from pipeline.montagem_longa import montar_video_longo
from pipeline.escritor import (
    contar_palavras_faladas,
    gerar_roteiro,
    reescrever_para_duracao,
    selecionar_trend,
    selecionar_trends_longo,
)
from pipeline.legendas import gerar_legendas
from pipeline.manchetes import instantes_das_viradas, planejar_partes
from pipeline.midia_x import baixar_midias_posts, descrever_midias
from pipeline.registro import registrar
from pipeline.seo import (
    capitulos,
    montar_descricao,
    panorama_do_dia,
    titulos_do_dia,
)
from pipeline.silencio import aparar_silencios, inserir_pausas
from pipeline.thumbnail import gerar_thumbnail
from pipeline.triagem import triar_material
from pipeline.x_client import (
    autorizar_x,
    buscar_posts_com_video,
    coletar_trends,
    renovar_token_do_x,
)
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.referencia import montar_dossies
from pipeline.youtube import top_retencao, ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o vídeo de notícias do dia.")
    parser.add_argument(
        "-usa",
        action="store_true",
        help="Conteúdo 100%% dedicado ao público americano (tudo em inglês)",
    )
    parser.add_argument(
        "--long-take",
        action="store_true",
        help=(
            "Vídeo LONGO de análise: 16:9, de 90 a 120 segundos, sem legendas "
            "(combina com -usa)"
        ),
    )
    parser.add_argument(
        "--auth-youtube",
        action="store_true",
        help="Autoriza o canal português e salva o refresh token no .env",
    )
    parser.add_argument(
        "--auth-youtube-usa",
        action="store_true",
        help="Autoriza o canal inglês e salva YOUTUBE_REFRESH_TOKEN_USA no .env",
    )
    parser.add_argument(
        "--auth-x",
        action="store_true",
        help=(
            "NÃO gera vídeo: autoriza o app do X no navegador (PKCE) com os "
            "escopos que o pipeline usa — inclusive `like.read`, sem o qual a "
            "pauta não sai das curtidas — e distribui os tokens aos crons"
        ),
    )
    parser.add_argument(
        "--renovar-x-token",
        action="store_true",
        help=(
            "NÃO gera vídeo: só renova o token do X e o distribui para os crons "
            "(cron dedicado; ver renovar_token_do_x em x_client.py)"
        ),
    )
    args = parser.parse_args()

    # Os modos que NÃO coletam pauta (renovar o token do X, autorizar o
    # YouTube) não precisam de X_LIST_ID — e o serviço do cron renovador não
    # tem essa env var. Exigir a lista deles derrubaria o cron que mantém o
    # token vivo para os outros quatro.
    coleta = not (
        args.renovar_x_token
        or args.auth_youtube
        or args.auth_youtube_usa
        or args.auth_x
    )
    cfg = carregar_config(exige_lista=coleta)
    if args.auth_youtube or args.auth_youtube_usa:
        autenticar_youtube(cfg, usa=args.auth_youtube_usa)
        return
    # AUTORIZAÇÃO DO X (2026-08-28). Roda LOCALMENTE, não em cron: depende de
    # um navegador. É o que faltava no repo — a autorização do X era feita à
    # mão, e a conta veio com as curtidas, que exigem um escopo (`like.read`)
    # que o token em produção não tinha. Ver `autorizar_x` em x_client.py.
    if args.auth_x:
        autorizar_x(cfg)
        return
    # Modo RENOVADOR (2026-08-18, ideia do usuário). Sai antes de qualquer
    # leitura paga: este cron existe só para ser o ÚNICO que renova o token do
    # X, acabando com a corrida entre os quatro crons de vídeo.
    if args.renovar_x_token:
        raise SystemExit(0 if renovar_token_do_x(cfg) else 1)
    if args.usa:
        cfg.publico = "usa"
        print("[config] Modo USA: conteúdo em inglês para o público americano")

    if args.long_take:
        ativar_formato_longo(cfg)
        print(
            f"[config] Formato LONGO: {cfg.video_largura}x{cfg.video_altura} "
            f"(16:9), teto de {cfg.video_duracao}s (máximo do formato: "
            f"{LONGO_MAX_S}s; a duração sai do material das pautas), "
            f"{LONGO_NUM_TRENDS} pautas, clipe de "
            f"{cfg.longo_min_dur_clipe_s}-{cfg.longo_max_dur_clipe_s}s, até "
            f"{cfg.max_clipes} clipes, sem legendas"
        )

    # Leituras do canal PRIMEIRO (fail-fast): se as credenciais do YouTube
    # estiverem quebradas, aborta antes de qualquer chamada paga (X, OpenAI) —
    # e sem os recentes (com as métricas) a seleção pela audiência é cega.
    recentes = ultimos_publicados(cfg, n=100)
    # Sem número aqui: no Short a lista não tem teto e o n_fallback nem chega a
    # ser usado (régua estrita, 2026-08-22); no longo o default dele resolve o
    # caminho de exceção.
    campeoes = top_retencao(cfg)
    # DOSSIÊ DOS CAMPEÕES (2026-08-22, pedido do usuário), só no Short e nos
    # dois canais: lê a legenda publicada e a capa de cada campeão, anexando
    # tudo à mesma lista que já segue para a seleção da trend e para o roteiro. Falha aberta — a régua numérica
    # sozinha é o comportamento que existia antes do dossiê, e ele não vale
    # derrubar uma execução.
    if cfg.formato == "curto" and campeoes:
        try:
            montar_dossies(cfg, campeoes)
        except Exception as erro:  # noqa: BLE001 — enriquecimento, não requisito
            print(
                f"[aviso] Dossiê dos campeões falhou ({erro}); a seleção segue "
                "só com as métricas."
            )

    def preparar_pauta(so_lista: bool = False) -> tuple[list[dict], bool]:
        """Coleta, classifica e tria as candidatas; (trends, a lista foi lida).

        Uma função porque roda DUAS vezes desde 2026-08-29: a segunda quando o
        material das curtidas não passa nos vetos e a lista do X assume (ver o
        laço de fallback abaixo).
        """
        # `recentes` vai junto porque as DESCRIÇÕES dele são a memória do que
        # já foi consumido: o post do X que já virou vídeo sai da disputa antes
        # da classificação (ver `x_client.posts_ja_usados`).
        brutas, usou = coletar_trends(
            cfg, so_lista=so_lista, videos_publicados=recentes
        )
        brutas = classificar_trends(cfg, brutas)
        # SÓ PAUTA DE MACROTEMA DEFINIDO (2026-08-28, pedido do usuário): a
        # candidata que caiu no balde "outro" sai da disputa. Ver
        # `filtrar_por_macrotema` — a justificativa mecânica dele (o balde
        # escapava do rodízio) caiu junto com o rodízio em 2026-08-29.
        brutas = filtrar_por_macrotema(brutas)

        # TRIAGEM DO MATERIAL (2026-08-18, pedido do usuário): conferir o clipe
        # ANTES de escolher a pauta. O sinal que a seleção tinha era indireto —
        # quantos posts da candidata têm clipe —, e ele não diz nada sobre o que
        # o clipe MOSTRA; o resultado eram execuções inteiras gastas para
        # descobrir na auditoria que o único clipe era busto falante. Falha aqui
        # não impede nada: candidata sem veredito disputa como antes.
        pasta_triagem = "_triagem_lista" if so_lista else "_triagem"
        try:
            triar_material(cfg, brutas, cfg.output_dir / pasta_triagem)
        except SystemExit:
            raise
        except Exception as erro:
            print(
                f"[aviso] Triagem do material falhou ({erro}); seguindo sem ela."
            )
        return brutas, usou

    trends, usou_lista = preparar_pauta()

    # FALLBACK DE TEMA (2026-08-05): a trend é escolhida por um sinal INDIRETO
    # de material — quantos posts dela têm clipe nativo —, e esse sinal erra:
    # o clipe pode não baixar e a auditoria pode reprovar tudo. Quando isso
    # acontecia a execução morria com exit 1, tendo pago a coleta e a
    # classificação e com outras candidatas vivas na lista. Agora a candidata
    # que não rende material sai da disputa e a próxima é tentada, até
    # TENTATIVAS_TREND.
    #
    # O laço fecha ANTES do TTS de propósito: as falhas cobertas aqui são as de
    # material, e refazê-las custa notícias + roteiro + visão, nunca narração.
    # Não há mais nenhum piso de duração abortando lá embaixo (2026-09-01): o
    # que sobra depois do TTS é o ajuste de velocidade e, se a faixa dele não
    # fechar, a reescrita do texto pelo ritmo MEDIDO — o mesmo tema, o mesmo
    # material, só o tamanho corrigido.
    tentadas: list[dict] = []
    # Alvo de fábrica (VIDEO_DURACAO / LONG_DURACAO). Nos DOIS formatos ele é o
    # MÁXIMO, não a meta: cada tentativa recalcula o alvo a partir da metragem
    # da pauta escolhida, e sem guardar o valor original a segunda tentativa
    # herdaria o alvo encolhido da primeira.
    duracao_alvo = cfg.video_duracao
    # SEGUNDA FONTE NO LAÇO (2026-08-29, pedido do usuário: "qualquer erro ou
    # filtro nos likedposts, fallback para a lista"). Até aqui a lista só
    # entrava por ESCASSEZ na coleta — uma contagem feita antes de qualquer
    # visão. Os vetos rodam quatro etapas depois, e quando eles reprovavam tudo
    # a execução abortava com a lista intocada: foi o que aconteceu nas 10
    # falhas de 27 a 29/08. Agora, esgotadas as TENTATIVAS_TREND candidatas das
    # curtidas, a lista é lida (+US$ 0,50 numa execução que hoje não produz
    # nada) e o laço recomeça com a pauta dela.
    lista_pendente = bool(cfg.x_list_id) and not usou_lista
    tentativa = 0
    while True:
        tentativa += 1
        if tentativa > TENTATIVAS_TREND:
            if not lista_pendente:
                raise SystemExit(
                    f"As {TENTATIVAS_TREND} candidatas tentadas não renderam "
                    "material aproveitável em NENHUMA das duas fontes — nem "
                    "nas curtidas nem na lista do X; abortando sem publicar. "
                    "Se isso virar rotina, a alavanca é pôr na lista do X (e "
                    "curtir) contas que publiquem VÍDEO filmado."
                )
            lista_pendente = False
            print(
                f"[fallback] As {TENTATIVAS_TREND} candidatas das curtidas "
                "foram reprovadas na auditoria; lendo a LISTA do X e "
                "recomeçando com a pauta dela."
            )
            trends, _ = preparar_pauta(so_lista=True)
            if not trends:
                raise SystemExit(
                    "A lista do X não devolveu candidata alguma depois de as "
                    "curtidas falharem; abortando sem publicar."
                )
            # Pauta nova, disputa nova: as excluídas eram das curtidas.
            tentadas = []
            tentativa = 1
        cfg.video_duracao = duracao_alvo
        # O LONGO cobre LONGO_NUM_TRENDS acontecimentos (2026-08-18, pedido do usuário),
        # um por tópico: exigir 4 posts com clipe de um mesmo fato nunca
        # passava, e com três assuntos cada um só precisa do próprio clipe.
        # A seleção ABORTA quando as regras duras zeram as candidatas (todas
        # já tentadas, todas repetindo vídeo publicado, nenhuma com clipe).
        # Com a lista ainda por ler isso não é fim de execução, é fim da FONTE:
        # o pedido de 2026-08-29 é que qualquer erro ou filtro das curtidas caia
        # para a lista, e ficar sem candidata é o filtro mais duro de todos.
        try:
            selecao = (
                selecionar_trends_longo(
                    cfg, trends, videos_recentes=recentes, campeoes=campeoes,
                    excluir=tentadas,
                )
                if cfg.formato == "longo"
                else selecionar_trend(
                    cfg, trends, videos_recentes=recentes, campeoes=campeoes,
                    excluir=tentadas,
                )
            )
        except SystemExit:
            if not lista_pendente:
                raise
            print(
                "[fallback] A seleção ficou sem candidata nas curtidas; "
                "passando para a lista do X."
            )
            tentativa = TENTATIVAS_TREND
            continue
        # SEO/GEO: quem MAIS publicou sobre este assunto hoje. É a única leitura
        # do pipeline sobre o lado de fora do canal — os últimos publicados e os
        # campeões de retenção calibram o tom com o próprio público, mas não
        # dizem nada sobre a disputa da busca. Fica DENTRO do laço porque cada
        # tentativa é outra pauta, e a concorrência de uma não serve para a
        # outra. Falha aberta: sem panorama o roteiro sai como saía antes.
        panorama = panorama_do_dia(
            cfg, selecao.get("consulta_youtube") or selecao["trend"]
        )

        # APURAÇÃO (2026-08-30, pedido do usuário: "o roteiro fala direto que
        # não dá para saber X, não dá para saber Y; isso degrada muito a
        # experiência da audiência"). Busca na web o que o post do X não conta
        # — o número, o quanto era antes, quem paga, qual o próximo marco — e
        # entrega ao roteirista com o veículo e a URL de cada fato, conferidos
        # em código contra as páginas que a busca abriu (ver apuracao.py).
        #
        # Fica DENTRO do laço, ao lado do panorama e pelo mesmo motivo: cada
        # tentativa é outra pauta, e apuração de uma não serve para a outra.
        # DEPOIS da seleção porque só aqui se sabe qual é a pauta, e ANTES do
        # roteiro porque é o roteiro que precisa nascer com o dado na mão.
        # Falha aberta: sem dossiê o roteiro sai como saía antes desta data.
        dossie = apurar(cfg, selecao.get("trend_obj") or {"trend": selecao["trend"]})

        # O MATERIAL DIMENSIONA O ROTEIRO (2026-08-28, pedido do usuário: "não
        # coloque o vídeo em loop várias vezes, em vez disso, adeque o roteiro
        # dentro do que cabe naquele vídeo selecionado da pauta").
        #
        # VALE NOS DOIS FORMATOS desde 2026-09-01 ("sempre priorizar o tamanho
        # do material"). O longo era a exceção — alvo fixo na faixa de 120-150s
        # e clipe repetido em loop para cobri-la — e agora é dimensionado pela
        # soma das pautas, cada uma pelo clipe DELA (`alvos_das_pautas`).
        # É essa conta por capítulo que tira o loop do formato: pauta de clipe
        # curto vira parte curta em vez de parte repetida.
        #
        # Vem DEPOIS da seleção porque só aqui se sabe QUAL pauta é, e ANTES do
        # roteiro porque é o roteiro que precisa nascer do tamanho certo — a
        # faixa de palavras (`_faixa_palavras`, escritor.py) é calculada em
        # cima de cfg.video_duracao. `alvo_pelo_material` nunca devolve None
        # aqui: a candidata sem metragem já saiu no portão da seleção.
        # A METRAGEM QUE ENTRA AQUI É A APROVEITÁVEL (2026-08-30). Antes vinha
        # `segundos_video`, a duração CHEIA do clipe informada pela X API — e a
        # conferência do fim deste laço mede outra coisa: `segundos_uteis`, que
        # desconta a abertura de busto falante que a montagem descarta. Com
        # duas réguas diferentes e a mesma MATERIAL_MARGEM dos dois lados, todo
        # clipe com ponta a cortar era reprovado por exatamente o tamanho da
        # ponta: na execução BR de 30/08 o clipe do DHL Stadium foi aprovado
        # com nota 5 e descartado assim mesmo, 13,6s de útil contra 13,8s
        # exigidos, porque o roteiro nascera dos 14,6s do arquivo.
        #
        # O número vem da TRIAGEM, que já rodou a visão nesta candidata antes
        # da escolha (triagem.py) — não há medida nova a pagar. Ela mede UM
        # clipe de amostra e a montagem pode acabar com mais de um, então o
        # alvo sai conservador: o roteiro pode ficar mais curto do que caberia,
        # nunca mais comprido. Errar para baixo custa segundos de vídeo; errar
        # para cima custa a pauta inteira.
        #
        # Candidata sem triagem (fora do teto de MAX_CANDIDATAS, download ou
        # visão falhos) cai na duração cheia, como era antes: medida faltando é
        # ignorância nossa, e não é motivo para encolher vídeo.
        pautas_s: list[int] | None = None
        if cfg.formato == "curto":
            trend_obj = selecao["trend_obj"]
            metragem = trend_obj.get("segundos_uteis") or trend_obj.get(
                "segundos_video"
            )
            alvo = alvo_pelo_material(cfg, metragem)
            if alvo is not None and alvo < cfg.video_duracao:
                print(
                    f"[material] A pauta tem ~{float(metragem or 0):.0f}s de "
                    f"clipe aproveitável; o roteiro passa a mirar {alvo}s em "
                    f"vez de {cfg.video_duracao}s (o Short não repete clipe "
                    "em loop)."
                )
                cfg.video_duracao = alvo
        else:
            # As pautas do longo, na ordem em que virarão os tópicos.
            # `selecoes` vem de `selecionar_trends_longo`; a lista de um
            # elemento cobre a chamada antiga de uma trend só.
            #
            # A lista é COMPLETADA até LONGO_NUM_TRENDS com None de propósito:
            # o roteiro tem sempre LONGO_NUM_TRENDS tópicos, e uma lista curta aqui
            # dimensionaria o vídeo para menos pautas do que ele vai ter. None
            # não é medida faltando por descuido — `alvos_das_pautas` dá a ele
            # a mediana das medidas que existem.
            escolhidas = [
                s["trend_obj"] for s in (selecao.get("selecoes") or [])
            ] or [selecao["trend_obj"]]
            metragens = [
                t.get("segundos_uteis") or t.get("segundos_video")
                for t in escolhidas
            ]
            metragens += [None] * max(0, LONGO_NUM_TRENDS - len(metragens))
            alvo, pautas_s = alvos_das_pautas(cfg, metragens)
            print(
                "[material] Cada pauta dura o que o clipe dela dá: "
                + ", ".join(
                    f"pauta {k} ~{s}s" for k, s in enumerate(pautas_s, 1)
                )
                + f" (+ ~{int(alvo - sum(pautas_s))}s de abertura) = vídeo de "
                f"~{alvo}s, teto {cfg.video_duracao}s."
            )
            cfg.video_duracao = alvo

        roteiro = gerar_roteiro(
            cfg, selecao, trends,
            videos_recentes=recentes, campeoes=campeoes, panorama=panorama,
            apuracao=dossie, pautas_s=pautas_s,
        )

        marca = "_longo" if cfg.formato == "longo" else ""
        pasta = (
            cfg.output_dir
            / f"{datetime.now():%Y-%m-%d}{marca}_{_slug(roteiro['titulo'])}"
        )
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "roteiro.json").write_text(
            json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # O OBJETO da trend vem da própria seleção (selecionar_trend) — é o
        # mesmo que o roteiro usou, então os clipes baixados são sempre da
        # trend certa.
        trend_video = selecao["trend_obj"]

        # Busca ABERTA por clipes do assunto (só no formato longo, por
        # X_MAX_POSTS_BUSCA=0 no curto): as contas seguidas raramente têm vários
        # clipes do MESMO fato — só 5,6% dos posts delas trazem vídeo —, e é
        # disso que 90-120s de tela precisam. Fica fora do Short porque as
        # fontes não são curadas e o crédito leva a @ delas para a tela, 12
        # vezes por dia. Entra depois da seleção porque buscar para cada
        # candidata custaria uma consulta por candidata — em troca, a busca não
        # socorre uma candidata que já tenha sido barrada no portão da seleção.
        extras = buscar_posts_com_video(cfg, selecao.get("consulta_clipes", ""))
        if extras:
            urls = trend_video.get("posts") or []
            # `posts` vem com os posts de vídeo na frente (x_client), e o
            # lookup de mídias corta a lista no teto — então os achados entram
            # logo depois deles, antes dos posts só de texto, senão seriam
            # cortados fora.
            n_video = trend_video.get("posts_com_video") or 0
            novos = [u for u in extras if u not in urls]
            trend_video["posts"] = urls[:n_video] + novos + urls[n_video:]
            trend_video["posts_com_video"] = n_video + len(novos)

        clipes, fotos = baixar_midias_posts(
            cfg, trend_video.get("posts") or [], pasta
        )
        piso = LONGO_MIN_CLIPES_APROVADOS if cfg.formato == "longo" else 1
        if not clipes:
            recusa = (
                "nenhum clipe de vídeo baixou dos posts da trend (o formato é "
                "montado só com clipes do X, imagem estática é proibida)"
            )
        else:
            # AUDITORIA do material visual, antes do ElevenLabs: o GPT com
            # visão descreve e classifica cada clipe do pool, o veto duro
            # derruba material de telejornal/emissora e a nota de pertinência
            # derruba o clipe que não mostra o que a narração diz. Rodar aqui
            # (e não depois da narração, como a descrição das mídias rodava)
            # faz a reprovação custar zero crédito de TTS.
            laudos = descrever_midias(cfg, clipes)
            clipes = auditar_midias(
                cfg, roteiro["texto_video"], clipes, laudos,
                limite=cfg.max_clipes, rotulo="clipe", pasta=pasta,
            )
            recusa = ""
            if len(clipes) < piso:
                recusa = (
                    f"a auditoria aprovou {len(clipes)} clipe(s), abaixo do "
                    f"piso de {piso} do formato {cfg.formato} — o vídeo sairia "
                    "mostrando material de telejornal ou cena que não condiz "
                    f"com a narração (detalhe em "
                    f"{pasta / 'auditoria_clipe.json'})"
                )
            # SEGUNDA CONFERÊNCIA DA METRAGEM, agora sobre o que a auditoria
            # DEIXOU (2026-08-28). A primeira (o portão da seleção) contou o
            # que a X API prometeu; esta conta o que sobrou depois do veto e do
            # trecho útil de cada clipe, que é o que de fato vai à tela.
            #
            # Ela é o que impede o Short de voltar a repetir clipe por outra
            # porta: aprovar um clipe de 8s para um roteiro de 25 daria
            # exatamente o loop que o pedido tirou. Cai no FALLBACK DE TEMA
            # (a candidata perde a vez) porque ainda estamos antes do TTS —
            # custa notícias, roteiro e visão, nunca narração.
            #
            # Só conta quando TODOS os aprovados foram medidos: com um clipe
            # sem `dur_s` (ffprobe falhou) a soma sairia menor que a verdade e
            # derrubaria uma pauta que tinha material. Medida faltando é
            # ignorância nossa, e ignorância não veta pauta em nenhum outro
            # ponto deste pipeline.
            elif cfg.formato == "curto" and all(m.get("dur_s") for m in clipes):
                tela = sum(segundos_uteis(m) for m in clipes)
                preciso = cfg.video_duracao * MATERIAL_MARGEM
                if tela < preciso:
                    recusa = (
                        f"os {len(clipes)} clipe(s) aprovados somam "
                        f"{tela:.0f}s de trecho útil, e o roteiro de "
                        f"{cfg.video_duracao}s precisa de ~{preciso:.0f}s — o "
                        "Short não repete mais clipe em loop, então a tela "
                        "ficaria sem imagem no fim"
                    )
        if not recusa:
            break

        # Descarta TODAS as escolhidas da rodada: no longo são várias, e repetir
        # uma delas na tentativa seguinte gastaria material já reprovado.
        if selecao.get("selecoes"):
            tentadas.extend(s["trend_obj"] for s in selecao["selecoes"])
        else:
            tentadas.append(trend_video)
        print(
            f"[fallback] Tentativa {tentativa}/{TENTATIVAS_TREND} descartada — "
            f"'{selecao['trend']}': {recusa}."
        )
        if tentativa < TENTATIVAS_TREND:
            print("[fallback] Escolhendo outra trend com o material restante.")

    marcar_memoria("antes da narração")

    # NARRAR, MEDIR E — SE NÃO COUBE — REFAZER O TEXTO (2026-09-01, pedido do
    # usuário: "se estourar ou ficar abaixo, coloque para refazer").
    #
    # Até aqui a duração do vídeo era decidida em PALAVRAS e conferida depois
    # dos fatos: o orçamento de palavras usava PALAVRAS_POR_SEGUNDO, que é a
    # média de dez narrações, e o TTS varia ±11% em torno dela. Esse erro era
    # absorvido pela velocidade, que não tinha limite — dava para esticar o
    # áudio o quanto fosse preciso. Com a faixa de 1,00x a 1,15x pedida agora,
    # não dá mais, e a alavanca que sobra é a certa: o TEXTO.
    #
    # A segunda tentativa não é um chute repetido. A primeira narração deu o
    # ritmo REAL desta voz com este texto (palavras / duração medida), e é por
    # ele que o novo tamanho é encomendado — a conversão deixa de ser média e
    # vira medida, então uma tentativa costuma bastar.
    #
    # SÓ NO SHORT. O longo narra em 1.0x por decisão editorial e não tem faixa
    # de velocidade para estourar; o tamanho dele é resolvido antes, pela
    # duração flexível de cada capítulo.
    for tentativa_audio in range(1, TENTATIVAS_NARRACAO + 1):
        narracao, alinhamento = gerar_narracao(
            cfg, roteiro["texto_video"], pasta / "narracao.mp3"
        )
        narracao, alinhamento, dur_narracao = aparar_silencios(
            narracao, alinhamento
        )
        if cfg.formato != "curto":
            coube = True
            break

        # A duração ANTES do ajuste é a que mede o ritmo desta voz na
        # velocidade de BASE — depois do ajuste ela já traz a correção dentro.
        palavras_narradas = contar_palavras_faladas(roteiro["texto_video"])
        dur_na_base = dur_narracao
        alinhamento, dur_narracao, coube = ajustar_ao_alvo(
            narracao,
            alinhamento,
            float(cfg.video_duracao),
            dur_narracao,
            base=cfg.velocidade,
            minimo=CURTO_VELOCIDADE_MIN,
            maximo=CURTO_VELOCIDADE_MAX,
        )
        if coube or tentativa_audio == TENTATIVAS_NARRACAO:
            break

        # Ritmo MEDIDO, em palavras por segundo de áudio NA VELOCIDADE DE BASE.
        # Encomendar o novo texto por ele faz a segunda narração cair no alvo
        # já em 1,05x, sem precisar do ajuste — em vez de cair no alvo presa na
        # borda da faixa, que é o que sairia se a medida viesse do áudio já
        # acelerado.
        ritmo = palavras_narradas / max(dur_na_base, 0.1)
        roteiro = reescrever_para_duracao(
            cfg,
            roteiro,
            max(1, int(cfg.video_duracao * ritmo)),
            f"tentativa {tentativa_audio}/{TENTATIVAS_NARRACAO} de fechar "
            f"{cfg.video_duracao}s dentro da faixa de velocidade",
        )
        (pasta / "roteiro.json").write_text(
            json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if cfg.formato == "curto" and not coube:
        print(
            f"[aviso] Depois de {TENTATIVAS_NARRACAO} narração(ões) o vídeo "
            f"ficou em {dur_narracao:.1f}s contra o alvo de "
            f"{cfg.video_duracao}s; seguindo — a MATERIAL_MARGEM da montagem "
            "cobre a diferença."
        )

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + RESPIRO_FINAL

    # NÃO HÁ MAIS PISO DE DURAÇÃO EM NENHUM FORMATO (2026-09-01, pedido do
    # usuário). O do Short saiu em 28/08; o do longo (LONGO_MIN_S=120) saía
    # aqui, com SystemExit, DEPOIS da narração já paga — e era ele que
    # transformava "as pautas de hoje tinham clipe curto" em execução
    # perdida. Com o material dimensionando o roteiro nos dois formatos, vídeo
    # curto virou o resultado certo para um dia de material curto.
    #
    # O TETO fica, e continua só avisando: vídeo comprido demais é defeito de
    # retenção, não de formato, e jogar fora uma execução inteira por 3
    # segundos de fala a mais seria caro sem ninguém ganhar nada.
    if cfg.formato == "longo" and duracao > LONGO_MAX_S:
        print(
            f"[aviso] Narração de {duracao:.1f}s acima do teto do formato "
            f"longo ({LONGO_MAX_S}s); o vídeo segue, mas vale ajustar "
            "LONG_DURACAO se isso virar rotina."
        )

    # --- Daqui para baixo o formato longo tem um caminho PRÓPRIO --------------
    #
    # O longo deixou de ser "o Short com outros parâmetros" em 2026-08-25: ele
    # é montado em PARTES separadas (a abertura mais uma por pauta), coladas
    # no ffmpeg (montagem_longa.py). O que muda:
    #   - as pausas de virada não são mais um respiro editorial, são os PONTOS
    #     DE CORTE das partes, e `inserir_pausas` devolve onde cada uma ficou;
    #   - o planejador de cortes por citação sai de cena: cada pauta recebe UM
    #     clipe, escolhido por `atribuir_clipes`, e nenhum clipe serve a duas;
    #   - cartelas e legendas continuam fora (as cartelas saíram agora, com o
    #     resto: foto tomando o quadro no meio de uma pauta é a pauta sem o
    #     vídeo dela).
    if cfg.formato == "longo":
        # PAUSA NAS TROCAS DE PAUTA: abre um silêncio logo ANTES da frase de
        # virada de cada pauta. Fica DEPOIS da conferência de piso de propósito:
        # o piso mede FALA, e somar silêncio à duração deixaria um roteiro curto
        # demais passar por causa do respiro.
        narracao, alinhamento, pausas = inserir_pausas(
            narracao,
            alinhamento,
            instantes_das_viradas(
                roteiro, roteiro["texto_video"], alinhamento, duracao
            ),
            cfg.pausa_pauta_s,
        )
        duracao = duracao_audio(narracao) + RESPIRO_FINAL

        # As partes, com o painel de texto de cada uma. Aborta se a
        # divisão não fechar — sem ela o vídeo sairia como o bloco corrido que
        # o formato deixou de ser.
        partes = planejar_partes(
            cfg, roteiro, pausas, duracao, pasta, tela=(largura, altura)
        )

        # UM CLIPE POR PAUTA, sem repetir. A abertura mostra todos em
        # sequência: ela é o "ainda neste vídeo" em imagem, a prévia do que foi
        # prometido no painel.
        midias = [
            {
                "caminho": m["caminho"],
                "tipo": m.get("tipo", ""),
                "dur_s": m.get("dur_s"),
                "conta": m.get("conta", ""),
                "representacao": bool(m.get("representacao")),
                "inicio_util_s": m.get("inicio_util_s"),
                "descricao": (
                    m.get("descricao")
                    or "clipe anexado a um post original da trend"
                ),
            }
            for m in clipes
        ]
        clipes_da_pauta = atribuir_clipes(cfg, roteiro, midias)
        clipes_por_parte = [clipes_da_pauta, *([c] for c in clipes_da_pauta)]

        marcar_memoria("antes da montagem")
        video_final = montar_video_longo(
            narracao,
            partes,
            clipes_por_parte,
            pasta / "video_final.mp4",
            largura,
            altura,
            publico=cfg.publico,
        )
        sobreposicoes = clipes_da_pauta
    else:
        # Posicionamento automático (reserva): clipes espalhados uniformemente,
        # com o primeiro abrindo o gancho.
        sobreposicoes = [
            {
                "caminho": m["caminho"],
                "inicio_frac": k / max(len(clipes), 1),
                "fim_frac": None,
                "conta": m.get("conta", ""),
                "representacao": bool(m.get("representacao")),
                "inicio_util_s": m.get("inicio_util_s"),
            }
            for k, m in enumerate(clipes)
        ]

        # Planejador de cortes: a IA casa cada clipe com o momento da narração.
        # Os clipes já vêm auditados, com a descrição da visão dentro de cada um
        # — descrever o arquivo real evita casar a narração com a cena errada e
        # melhora a escolha do primeiro clipe, o que decide o swipe.
        midias_plano = [
            {
                "caminho": m["caminho"],
                "tipo": m.get("tipo", ""),
                "dur_s": m.get("dur_s"),
                "conta": m.get("conta", ""),
                "descricao": (
                    m.get("descricao")
                    or "clipe anexado a um post original da trend"
                ),
            }
            for m in clipes
        ]
        plano = planejar_cortes(
            cfg, roteiro["texto_video"], midias_plano, alinhamento, duracao
        )
        if plano:
            # O plano volta só com caminho/tempos; a conta de origem (crédito de
            # reprodução na tela) e a marcação de representação visual são
            # reanexadas pelo caminho do arquivo.
            conta_por_caminho = {
                str(m["caminho"]): m.get("conta", "") for m in clipes
            }
            repr_por_caminho = {
                str(m["caminho"]): bool(m.get("representacao")) for m in clipes
            }
            util_por_caminho = {
                str(m["caminho"]): m.get("inicio_util_s") for m in clipes
            }
            for p in plano:
                p["conta"] = conta_por_caminho.get(str(p["caminho"]), "")
                p["representacao"] = repr_por_caminho.get(str(p["caminho"]), False)
                p["inicio_util_s"] = util_por_caminho.get(str(p["caminho"]))
            sobreposicoes = plano
            (pasta / "cortes.json").write_text(
                json.dumps(
                    [
                        {"midia": str(p["caminho"].name), "inicio_s": p["inicio_s"]}
                        for p in plano
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        legendas = gerar_legendas(
            roteiro["texto_video"],
            alinhamento,
            duracao,
            largura,
            altura,
            pasta / "legendas.ass",
            intervalos_imagens=intervalos_imagens(sobreposicoes, duracao),
        )

        # Cartelas: a foto do post da trend toma a tela inteira pelo deslize, no
        # lugar do clipe. Renderizada no tamanho do QUADRO desde a volta da tela
        # cheia (2026-08-16).
        cartelas = gerar_cartelas(
            cfg,
            roteiro["texto_video"],
            fotos,
            alinhamento,
            duracao,
            pasta,
            tela=(largura, altura),
        )

        marcar_memoria("antes da montagem")
        video_final = montar_video(
            narracao,
            sobreposicoes,
            pasta / "video_final.mp4",
            largura,
            altura,
            legendas=legendas,
            cartelas=cartelas,
            publico=cfg.publico,
            formato=cfg.formato,
        )

    # CAPÍTULOS (só no formato longo): cada tópico do roteiro trouxe uma citação
    # literal do ponto da narração em que ele começa, e o alinhamento converte
    # isso em carimbo de tempo. Publicados na descrição, viram os "momentos
    # principais" do YouTube — que rendem posição na busca e deixam o
    # espectador pular direto para o trecho que ele veio ver. Bloco inválido
    # (poucos capítulos, trechos colados) volta vazio e simplesmente não sai.
    marcos = []
    if cfg.formato == "longo":
        marcos = capitulos(
            roteiro, roteiro["texto_video"], alinhamento, duracao, cfg.publico
        )

    # A descrição publicada é montada aqui: o parágrafo do payload, o par P:/R:
    # (a parte de GEO — a frase que um buscador com IA consegue citar sem ter
    # assistido), os capítulos, as fontes reais do formato longo e, sempre por
    # último, as hashtags.
    descricao = montar_descricao(
        roteiro,
        cfg.publico,
        formato=cfg.formato,
        trend=trend_video,
        marcos=marcos,
        fontes_apuracao=(dossie or {}).get("urls"),
    )

    registrar(cfg, video_final, roteiro["titulo"], descricao)

    # Capa customizada (só no longo, onde a thumbnail decide o clique — no
    # Short o feed mostra o vídeo rodando). Falha aqui não aborta: o YouTube
    # cai na capa automática e o vídeo vai ao ar do mesmo jeito.
    #
    # Os quadros candidatos saem dos CLIPES, não do vídeo montado (2026-08-25):
    # desde que o painel de manchete ficou fixo na tela, todo frame do vídeo
    # montado traz o painel — e a capa é uma montagem em cima desse frame, com
    # recorte e desfoque, então o painel entraria dentro da capa.
    #
    # A CAPA ANUNCIA A PAUTA 1, e não uma qualquer (2026-08-26, pedido do
    # usuário). O vídeo longo cobre vários assuntos sem relação entre si; dando
    # ao modelo da capa a narração inteira e todos os clipes, ele escolhia o
    # material mais forte, que não é o que o título anuncia. Em 26/08 saiu a
    # capa "NEPAL LANDSLIDE KILLS 7" sobre o título "Flávio Bolsonaro Calls
    # Rally as Video Access Opens and Nepal Reports Deaths". Agora ele recebe
    # SÓ a fala da pauta 1 e SÓ o clipe dela: a coerência vem da construção, e
    # não de uma regra no prompt pedindo que ele se comporte.
    capa = None
    if cfg.formato == "longo":
        capa = gerar_thumbnail(
            cfg,
            video_final,
            roteiro["titulo"],
            texto_da_pauta(roteiro, 1),
            pasta,
            titulos_do_dia=titulos_do_dia(panorama),
            fontes=[Path(sobreposicoes[0]["caminho"])],
        )

    url_youtube = publicar_youtube(
        cfg,
        video_final,
        roteiro["titulo"],
        descricao,
        tags=roteiro.get("tags"),
        thumbnail=capa,
    )

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição:\n{descricao}")
    print(f"  YouTube: {url_youtube}")


if __name__ == "__main__":
    main()
