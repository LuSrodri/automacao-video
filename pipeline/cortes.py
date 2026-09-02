"""Planejamento dos cortes: a IA decide quando cada clipe entra e quanto fica.

O modelo recebe a narração e os clipes de vídeo disponíveis (os aprovados pela
auditoria, todos dos posts do X da trend, com as descrições do GPT com visão
sobre os arquivos baixados) e devolve a sequência de cortes. A regra 5 abaixo
ainda manda omitir clipe fora do assunto, mas ela virou rede de segurança: o
descarte de material impróprio é responsabilidade da auditoria (auditoria.py),
que roda antes e não devolve o clipe reprovado ao fallback. Cada corte é
ancorado numa
CITAÇÃO EXATA do texto da narração — nunca em segundos, que LLM chuta — e a
citação é convertida em tempo real pelos timestamps por caractere do
alinhamento do ElevenLabs (já remapeados após o corte de silêncios).

Qualquer falha (resposta inválida, citações não encontradas, poucos cortes)
devolve None e o main.py cai no posicionamento automático de sempre.

ISSO VALE PARA `planejar_cortes`, do SHORT. O FORMATO LONGO tem outra pergunta
e outra política, em `atribuir_clipes`: lá não é "em que segundo este clipe
entra", é "qual clipe é o da pauta 1, qual é o da 2, qual é o da 3", e o
resultado é obrigatório — cada pauta mostra o SEU clipe do começo ao fim dela.
Por isso ali nada degrada: faltou clipe, o clipe não tem a ver com a pauta ou a
chamada não fecha, a execução ABORTA. O fallback que parcava por duração saiu
em 2026-08-26 junto com o piso de pertinência (PERTINENCIA_MINIMA): ele era o
caminho que entregava justamente o pareamento cego que o piso existe para
barrar.
"""

import json
import re
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Audio tags da ElevenLabs — "[curioso]", "[pausa]" — que o roteirista escreve
# no meio do texto. Elas VÃO para o TTS (o alinhamento traz os caracteres
# delas), mas ninguém as fala, e o modelo que copia uma citação do texto pula
# por cima delas: a citação "o dinheiro explica a pressa" existe no roteiro
# como "o dinheiro [pausa] explica a pressa". Buscar literal no texto cru
# perdia esses casos, e cada perda é um corte a menos.
AUDIO_TAG = re.compile(r"\[[^\]]*\]")

# Mínimo de cortes válidos para aceitar o plano (abaixo disso, fallback). Com
# até 3 clipes, ficar num único clipe forte o vídeo inteiro é escolha
# editorial legítima — só o plano VAZIO (resposta inútil) cai no fallback.
MIN_CORTES = 1

ESQUEMA_CORTES = {
    "name": "plano_de_cortes",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cortes": {
                "type": "array",
                "description": (
                    "A sequência de cortes do vídeo, em ordem cronológica da "
                    "narração."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "midia": {
                            "type": "string",
                            "description": "id da mídia escolhida (ex.: m3)",
                        },
                        "entra_em": {
                            "type": "string",
                            "description": (
                                "citação EXATA e curta (3 a 8 palavras "
                                "consecutivas) do texto da narração, copiada "
                                "caractere por caractere, marcando onde a "
                                "mídia entra"
                            ),
                        },
                    },
                    "required": ["midia", "entra_em"],
                },
            },
        },
        "required": ["cortes"],
    },
}

INSTRUCOES_CORTES = """\
Você é o EDITOR DE CORTES de um vídeo vertical curto (YouTube Shorts) narrado.

Você recebe o texto da NARRAÇÃO (com duração total) e os CLIPES DE VÍDEO
disponíveis (até 3, todos anexados aos posts originais do X sobre o fato),
cada um com um id, a duração e a descrição do que mostra. O vídeo é montado
SOMENTE com esses clipes — não há fotos.

Monte a sequência de cortes: qual clipe aparece, em que ordem e em que momento
da narração cada um ENTRA. Cada clipe fica na tela até o próximo entrar (o
último vai até o fim). Regras:

1. "entra_em" é uma citação EXATA e CURTA (3 a 8 palavras consecutivas) do
   texto da narração, copiada caractere por caractere, com a mesma pontuação e
   acentuação. NÃO parafraseie: a citação é localizada no texto por busca
   literal, e citação que não existir descarta o corte.
2. O primeiro corte DEVE citar as primeiras palavras da narração — o vídeo
   nunca começa sem clipe na tela. O primeiro clipe decide o "viewed vs
   swiped": abra com o clipe mais forte que couber no gancho.
3. CASE clipe e fala: o clipe entra quando a narração fala do que ele mostra.
   Com poucos clipes, divida a narração em blocos que façam sentido com o
   conteúdo de cada um — o momento da troca importa mais que a quantidade.
4. O CLIPE NÃO SE REPETE: ele toca uma vez, do começo ao fim, e acabou. Se você
   der a um clipe de 9 segundos uma janela de 18, ele não vai voltar ao início
   — a montagem encolhe a janela e desloca todos os cortes seguintes, desmontando
   o casamento entre clipe e fala que você acabou de fazer. Olhe a DURAÇÃO de
   cada clipe na lista e não dê a nenhum um trecho de narração mais longo do
   que ele.
5. RITMO (estime ~2,5 palavras por segundo): nenhum clipe fica menos de ~3s na
   tela, e as janelas NÃO precisam ser iguais — clipe forte segura 8 a 15s (se
   tiver essa duração), clipe de apoio resolve em 3 a 6s. Se possível, troque
   de clipe perto da virada da narração (fato → implicação) para renovar a
   atenção.
6. Clipe fora do assunto, redundante ou que só mostra logomarca: NÃO use
   (basta omitir — com 1 clipe bom e longo o suficiente o vídeo inteiro pode
   ficar nele). Não repita clipe.

Responda somente com o JSON pedido.\
"""

INSTRUCOES_CORTES_LONGO = """\
Você é o EDITOR DE CORTES de um vídeo de ANÁLISE em 16:9, de cerca de
{duracao} segundos, narrado e SEM legendas na tela.

Você recebe o texto da NARRAÇÃO (com duração total) e os CLIPES DE VÍDEO
disponíveis (até {max_clipes}, todos anexados aos posts originais do X sobre o
fato), cada um com um id, a duração e a descrição do que mostra. O vídeo é
montado SOMENTE com esses clipes — não há fotos nem imagens de banco.

Monte a sequência de cortes: qual clipe aparece, em que ordem e em que momento
da narração cada um ENTRA. Cada clipe fica na tela até o próximo entrar (o
último vai até o fim; clipe mais curto que a janela repete em loop). Regras:

1. "entra_em" é uma citação EXATA e CURTA (3 a 8 palavras consecutivas) do
   texto da narração, copiada caractere por caractere, com a mesma pontuação e
   acentuação. NÃO parafraseie: a citação é localizada por busca literal, e
   citação que não existir descarta o corte.
2. O primeiro corte DEVE citar as primeiras palavras da narração — o vídeo
   nunca começa sem clipe na tela. Abra com o clipe mais forte que couber no
   gancho.
3. USE TODOS OS CLIPES QUE PRESTAREM: dois minutos parados no mesmo clipe
   cansam. Mire em trocar a cada 8 a 20 segundos e distribua os cortes ao
   longo de toda a narração — o vídeo não pode ter todos os cortes no começo e
   um clipe único segurando a segunda metade.
4. CASE clipe e fala: o clipe entra quando a narração fala do que ele mostra.
   Troque de clipe nas viradas de assunto da narração (o fato → a leitura
   geopolítica → a tecnologia → o dinheiro → o efeito no emprego): a troca
   marca o novo bloco e renova a atenção.
5. Clipe fora do assunto, redundante ou que só mostra logomarca: NÃO use
   (basta omitir). Não repita clipe.

Responda somente com o JSON pedido.\
"""


def _rotulo(m: dict) -> str:
    """Linha de apresentação de um clipe para o modelo.

    A duração anunciada é a UTILIZÁVEL, não a do arquivo: a montagem entra pelo
    `inicio_util_s` (o começo do miolo sem busto falante) e o que vem antes
    nunca vai ao ar. A diferença passou a importar em 2026-08-28, quando o
    Short deixou de repetir clipe — o planejador precisa dimensionar as janelas
    pelo que existe de fato, e um clipe de 30s que começa a servir aos 12
    entrega 18, não 30.
    """
    dur = m.get("dur_s")
    if dur:
        util = max(0.0, float(dur) - float(m.get("inicio_util_s") or 0.0))
        tipo = f"CLIPE DE VÍDEO de {util:.0f}s aproveitáveis"
    else:
        tipo = "CLIPE DE VÍDEO"
    conta = f", post de {m['conta']}" if m.get("conta") else ""
    return f"[{tipo}{conta}] {m.get('descricao', '').strip()}"


def texto_falado(texto: str) -> tuple[str, list[int]]:
    """(texto sem as audio tags, índice de cada caractere dele no texto cru).

    O mapa é o que permite achar a citação no texto FALADO e ainda assim
    perguntar ao alinhamento o instante do caractere no texto CRU — que é o
    que foi enviado à ElevenLabs e o que o alinhamento indexa.
    """
    limpo: list[str] = []
    mapa: list[int] = []
    fim = 0
    for tag in AUDIO_TAG.finditer(texto):
        for i in range(fim, tag.start()):
            limpo.append(texto[i])
            mapa.append(i)
        fim = tag.end()
    for i in range(fim, len(texto)):
        limpo.append(texto[i])
        mapa.append(i)
    return "".join(limpo), mapa


def localizar_citacao(texto: str, citacao: str, inicio: int = 0) -> int | None:
    """Índice, no texto CRU, do primeiro caractere de `citacao` — ou None.

    Casa por espaços normalizados e ignorando audio tags, porque é assim que o
    modelo copia: ele lê o texto falado e devolve a frase falada. `inicio` é um
    cursor no texto cru, para uma citação repetida casar com a ocorrência
    DEPOIS do corte anterior em vez de sempre com a primeira.
    """
    trecho = " ".join((citacao or "").split()).lower()
    if not trecho:
        return None
    limpo, mapa = texto_falado(texto)
    # Espaços colapsados dos dois lados: quebra de linha no roteiro vira espaço
    # simples na citação copiada, e uma quebra a mais não pode custar um corte.
    compacto: list[str] = []
    indices: list[int] = []
    anterior_espaco = False
    for i, ch in enumerate(limpo):
        if ch.isspace():
            if anterior_espaco:
                continue
            compacto.append(" ")
            anterior_espaco = True
        else:
            compacto.append(ch.lower())
            anterior_espaco = False
        indices.append(i)
    agulha = "".join(compacto)

    # O cursor vem em coordenadas do texto cru; traduz para as do compacto.
    corte = 0
    for k, i in enumerate(indices):
        if mapa[i] >= inicio:
            corte = k
            break
    else:
        corte = len(indices)

    pos = agulha.find(trecho, corte)
    if pos < 0:
        pos = agulha.find(trecho)
    if pos < 0:
        return None
    return mapa[indices[pos]]


def texto_da_pauta(roteiro: dict, k: int) -> str:
    """O trecho da narração que pertence à pauta `k` (1-based), ou tudo.

    Recorta entre a `citacao` do tópico k e a do tópico k+1, com a mesma busca
    que define os CORTES do vídeo (`localizar_citacao`) — então o trecho aqui é
    exatamente a fala que roda dentro daquela parte do vídeo.

    Existe para a CAPA (2026-08-26, pedido do usuário). Um vídeo longo cobre
    três assuntos sem relação entre si, e dar a narração inteira ao modelo da
    capa é convidá-lo a anunciar um assunto enquanto o título anuncia outro:
    em 26/08 o canal US publicou uma capa "NEPAL LANDSLIDE KILLS 7" sobre um
    título que abre no comício do Flávio Bolsonaro. Recebendo só a fala da
    pauta 1, ele não tem como escolher outra — a coerência sai da CONSTRUÇÃO,
    não de uma regra no prompt pedindo que ele se comporte.

    Devolve o texto inteiro quando a estrutura não permite o recorte; a capa é
    acabamento e nunca aborta publicação (o que garante a citação é
    `escritor._conferir_estrutura_longa`, que roda antes da narração).
    """
    texto = roteiro.get("texto_video") or ""
    topicos = roteiro.get("topicos") or []
    if not (1 <= k <= len(topicos)):
        return texto
    inicio = localizar_citacao(texto, topicos[k - 1].get("citacao") or "")
    if inicio is None:
        return texto
    fim = len(texto)
    if k < len(topicos):
        seguinte = localizar_citacao(
            texto, topicos[k].get("citacao") or "", inicio + 1
        )
        if seguinte is not None and seguinte > inicio:
            fim = seguinte
    return texto[inicio:fim].strip() or texto


def _tempo_do_char(alinhamento: dict, texto: str, pos: int, dur_total: float) -> float:
    """Instante (s) em que o caractere `pos` do texto é falado.

    Usa os timestamps por caractere do ElevenLabs quando eles casam com o
    texto; senão, aproxima pela fração de caracteres (comportamento antigo).
    """
    chars = alinhamento.get("characters") or []
    inicios = alinhamento.get("character_start_times_seconds") or []
    if (
        chars
        and len(chars) == len(inicios)
        and "".join(chars) == texto
        and 0 <= pos < len(inicios)
    ):
        return float(inicios[pos])
    return pos / max(len(texto), 1) * dur_total


def planejar_cortes(
    cfg: Config,
    texto_video: str,
    midias: list[dict],
    alinhamento: dict,
    dur_total: float,
) -> list[dict] | None:
    """Planeja os cortes; devolve sobreposições com tempo explícito ou None.

    `midias`: [{"caminho": Path, "tipo": str, "descricao": str,
    "dur_s": float|None, "conta": str}, ...]. O retorno é compatível com
    `montar_video`: [{"caminho", "inicio_s", "inicio_frac", "fim_frac"}, ...].
    """
    if not midias:
        return None

    listagem = "\n".join(
        f"m{k}: {_rotulo(m)}" for k, m in enumerate(midias, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO ({dur_total:.0f}s, {len(texto_video.split())} palavras):\n"
        f"{texto_video}\n\n"
        f"MÍDIAS DISPONÍVEIS:\n{listagem}"
    )

    instrucoes = (
        INSTRUCOES_CORTES_LONGO.format(
            duracao=round(dur_total), max_clipes=cfg.max_clipes
        )
        if cfg.formato == "longo"
        else INSTRUCOES_CORTES
    )

    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[cortes] Planejando os cortes de {len(midias)} mídias...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_CORTES},
        )
        cortes = json.loads(resposta.choices[0].message.content)["cortes"]
    except Exception as erro:
        print(f"[aviso] Planejador de cortes falhou ({erro}); posicionamento automático")
        return None

    texto_baixo = texto_video.lower()
    plano: list[dict] = []
    usadas: set[int] = set()
    # Os cortes vêm em ordem cronológica; a busca avança um cursor para que
    # uma citação repetida no texto case com a ocorrência DEPOIS do corte
    # anterior, não sempre com a primeira.
    cursor = 0
    for corte in cortes:
        id_bruto = str(corte.get("midia", "")).strip().lstrip("m")
        try:
            indice = int(id_bruto) - 1
        except ValueError:
            continue
        if not 0 <= indice < len(midias) or indice in usadas:
            continue
        citacao = str(corte.get("entra_em", "")).strip().lower()
        pos = texto_baixo.find(citacao, cursor) if citacao else -1
        if pos < 0 and citacao:
            pos = texto_baixo.find(citacao)
        if pos < 0:
            print(f"[cortes] citação não encontrada, corte ignorado: \"{citacao}\"")
            continue
        cursor = pos + 1
        usadas.add(indice)
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        plano.append(
            {
                "caminho": midias[indice]["caminho"],
                "inicio_s": min(max(0.0, inicio), dur_total),
                "inicio_frac": min(max(0.0, inicio), dur_total) / max(dur_total, 0.01),
                "fim_frac": None,
            }
        )

    if len(plano) < min(MIN_CORTES, len(midias)):
        print(
            f"[aviso] Plano de cortes com só {len(plano)} corte(s) válido(s); "
            "posicionamento automático"
        )
        return None

    plano.sort(key=lambda p: p["inicio_s"])
    plano[0]["inicio_s"] = 0.0
    plano[0]["inicio_frac"] = 0.0
    resumo = ", ".join(
        f"{Path(p['caminho']).name}@{p['inicio_s']:.1f}s" for p in plano
    )
    print(f"[cortes] {len(plano)} cortes: {resumo}")
    return plano


# =============================================================================
# UM CLIPE POR PAUTA (formato longo, 2026-08-25)
# =============================================================================
# O planejador de cortes acima continua sendo o do SHORT. No formato longo ele
# deixou de ser usado: lá o vídeo virou partes fechadas
# (montagem_longa.py) e a pergunta mudou de "em que segundo cada clipe entra"
# para "qual clipe é o da pauta 1, qual é o da 2, e assim por diante".
#
# O usuário foi explícito: "para cada pauta, é obrigatório o vídeo. Um mesmo
# vídeo não pode servir para duas pautas." Por citação isso nunca teve garantia
# — o modelo casava o clipe com o trecho e o mesmo arquivo atravessava duas
# pautas —, então a atribuição virou um problema de PAREAMENTO, com o resultado
# conferido em código: uma pauta, um arquivo, todos diferentes.

ESQUEMA_ATRIBUICAO = {
    "name": "clipes_por_pauta",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "pautas": {
                "type": "array",
                "description": (
                    "Uma entrada por pauta, na MESMA ordem em que as pautas "
                    "foram apresentadas."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "pauta": {
                            "type": "integer",
                            "description": "número da pauta (1, 2, 3...)",
                        },
                        "midia": {
                            "type": "string",
                            "description": "id do clipe escolhido (ex.: m3)",
                        },
                        "porque": {
                            "type": "string",
                            "description": (
                                "em meia frase, o que este clipe MOSTRA que "
                                "tem a ver com esta pauta"
                            ),
                        },
                        "pertinencia": {
                            "type": "integer",
                            "description": (
                                "1 a 5: o quanto este clipe mostra A COISA "
                                "DESTA pauta. 5 = mostra o próprio "
                                "acontecimento dela; 4 = mostra o lugar, a "
                                "pessoa ou a empresa dela, em outro momento; "
                                "3 = mostra o MESMO TIPO de cena que ela "
                                "descreve, sem ser o caso dela; 2 = só tem a "
                                "ver por tema geral; 1 = não tem relação "
                                "nenhuma com esta pauta. A nota é HONESTA — "
                                "ver a regra 6."
                            ),
                        },
                    },
                    "required": ["pauta", "midia", "porque", "pertinencia"],
                },
            },
        },
        "required": ["pautas"],
    },
}

# PISO DE PERTINÊNCIA DO CLIPE DE CADA PAUTA (2026-08-26, pedido do usuário).
#
# Mesma escala de 1 a 5 de auditoria.NOTA_MINIMA, mas a pergunta é OUTRA: lá é
# "este clipe serve a este VÍDEO", aqui é "este clipe é o desta PAUTA". Um
# clipe pode passar lá e não ter nada a ver com a pauta em que caiu, e foi
# exatamente isso que saiu publicado no canal US em 26/08: o veto de live
# footage aprovou 6 clipes, TODOS da enchente no Nepal, e o pareamento pôs um
# deles no comício do Flávio e outro na API da Higgsfield — com o próprio
# modelo escrevendo no log "embora não mostre diretamente o software citado".
# Não havia piso: o pareamento abortava se FALTASSE clipe, nunca se o clipe não
# tivesse relação. Duas das três pautas ficaram dezenas de segundos mostrando
# outra coisa.
#
# 3 é o mesmo ponto de corte da auditoria: "mostra o mesmo TIPO de cena" ainda
# ilustra a pauta, "só tem a ver por tema geral" não. O custo é conhecido e
# aceito pelo usuário: dia sem imagem da pauta é dia sem vídeo longo.
PERTINENCIA_MINIMA = 3
# Uma segunda chance, com a lista das pautas reprovadas de volta no pedido: às
# vezes existe um pareamento melhor entre os mesmos clipes. Se o material não
# tem a imagem, a segunda também reprova — e aí é para abortar mesmo.
TENTATIVAS_ATRIBUICAO = 2

INSTRUCOES_ATRIBUICAO = """\
Você é o EDITOR de um vídeo de ANÁLISE em 16:9 dividido em partes fechadas.

Cada PAUTA do vídeo ocupa uma parte inteira e mostra UM ÚNICO CLIPE de vídeo
do começo ao fim dela. Sua tarefa é decidir qual clipe fica em qual pauta.

REGRAS DURAS:
1. Toda pauta recebe exatamente um clipe. Nenhuma fica sem.
2. NENHUM clipe pode ser usado em duas pautas. Se houver mais clipes do que
   pautas, os que sobram simplesmente não entram.
3. Escolha pelo que o clipe MOSTRA contra o que a pauta DIZ: o assunto, o
   lugar, a empresa, a cena, as pessoas. Clipe que mostra a coisa da pauta vale
   mais que clipe bonito.
4. O clipe da pauta fica DEZENAS DE SEGUNDOS na tela e repete em loop se for
   curto. Entre dois clipes igualmente pertinentes, prefira o mais LONGO e o
   que tem movimento — clipe curto e parado cansa antes do fim da pauta.
5. Pense no conjunto, não pauta por pauta: se o único clipe que serve para a
   pauta 3 também serviria para a pauta 1, dê-o à pauta 3 e resolva a 1 com
   outro. É melhor um pareamento razoável em todas do que um perfeito e dois
   ruins.
6. A NOTA DE PERTINÊNCIA É HONESTA, e é a regra que mais importa aqui. Ela não
   avalia o seu trabalho: ela decide se este vídeo pode existir. Nota abaixo de
   {piso} ABORTA a publicação — e abortar é o resultado CERTO quando o material
   coletado não tem imagem da pauta, porque o dia simplesmente não deu esse
   vídeo. Inflar a nota não conserta nada: publica um vídeo em que a pauta fala
   de uma coisa e a tela mostra outra por dezenas de segundos, que é pior do
   que não publicar. Se o melhor clipe que sobrou para uma pauta não mostra a
   coisa dela, dê a nota baixa e diga isso em `porque`. NÃO invente ligação
   ("é um vídeo dinâmico", "combina com o tom", "ilustra o clima", "dá ritmo"):
   isso é nota 1 ou 2 escrita como se fosse 4.

Responda somente com o JSON pedido.\
""".format(piso=PERTINENCIA_MINIMA)


def _ler_atribuicao(
    bruto: str, topicos: list[dict], midias: list[dict]
) -> dict[int, dict] | None:
    """{índice da pauta: {"midia", "porque", "pertinencia"}}, ou None.

    None quando a resposta não cobre TODAS as pautas com clipes diferentes —
    entrada repetida, fora de faixa ou ilegível é descartada em vez de aceita,
    porque a montagem exige um clipe por pauta e nenhum servindo a duas.
    """
    try:
        dados = json.loads(bruto)["pautas"]
    except (ValueError, KeyError, TypeError):
        return None

    pareamento: dict[int, dict] = {}
    vistos: set[int] = set()
    for item in dados:
        try:
            pauta = int(item.get("pauta", 0)) - 1
            indice = int(str(item.get("midia", "")).strip().lstrip("m")) - 1
            nota = int(item.get("pertinencia", 0))
        except (TypeError, ValueError):
            continue
        if not (0 <= pauta < len(topicos) and 0 <= indice < len(midias)):
            continue
        if pauta in pareamento or indice in vistos:
            continue
        pareamento[pauta] = {
            "midia": indice,
            "porque": str(item.get("porque", "")).strip(),
            "pertinencia": nota,
        }
        vistos.add(indice)
    return pareamento if len(pareamento) == len(topicos) else None


def atribuir_clipes(
    cfg: Config, roteiro: dict, midias: list[dict]
) -> list[dict]:
    """Devolve UM clipe por pauta do roteiro, sem repetir, e PERTINENTE.

    `midias`: [{"caminho": Path, "descricao": str, "dur_s": float|None,
    "conta": str, ...}, ...] — os clipes já aprovados pela auditoria. O retorno
    é a lista de mídias na ordem das pautas, com os campos originais
    preservados.

    Levanta SystemExit em três situações, todas por decisão do usuário e todas
    preferíveis a publicar:

      1. clipes aprovados em número menor que o de pautas — cada pauta é
         obrigada a ter o seu, e um mesmo clipe não pode servir a duas;
      2. o clipe de alguma pauta com pertinência abaixo de PERTINENCIA_MINIMA
         (2026-08-26): pauta cujo clipe não mostra a coisa dela é a tela
         contando outra história por dezenas de segundos;
      3. a chamada de pareamento falhando nas duas tentativas.

    A terceira era um FALLBACK até 2026-08-26: `_atribuicao_de_reserva` parear
    por duração, sem saber nada do assunto. Com o piso, ela virou um buraco —
    o caminho que entrega justamente o pareamento cego que o piso existe para
    barrar. Saiu.
    """
    topicos = roteiro.get("topicos") or []
    if len(midias) < len(topicos):
        raise SystemExit(
            f"O roteiro tem {len(topicos)} pauta(s) e a auditoria aprovou só "
            f"{len(midias)} clipe(s) — cada pauta é obrigada a ter o seu "
            "próprio vídeo, e um mesmo clipe não pode servir a duas; abortando "
            "sem publicar."
        )

    listagem = "\n".join(f"m{k}: {_rotulo(m)}" for k, m in enumerate(midias, 1))
    pautas = "\n".join(
        f"pauta {k}: {t.get('titulo', '')} — {t.get('dado', '')}"
        for k, t in enumerate(topicos, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"PAUTAS DO VÍDEO:\n{pautas}\n\n"
        f"CLIPES DISPONÍVEIS:\n{listagem}"
    )

    print(f"[cortes] Casando {len(midias)} clipe(s) com {len(topicos)} pauta(s)...")
    cliente = OpenAI(api_key=cfg.openai_api_key)
    mensagens: list[dict] = [
        {"role": "system", "content": INSTRUCOES_ATRIBUICAO},
        {"role": "user", "content": conteudo},
    ]

    problema = ""
    for tentativa in range(1, TENTATIVAS_ATRIBUICAO + 1):
        try:
            resposta = cliente.chat.completions.create(
                model=cfg.text_model,
                messages=mensagens,
                response_format={
                    "type": "json_schema",
                    "json_schema": ESQUEMA_ATRIBUICAO,
                },
            )
            bruto = resposta.choices[0].message.content
        except Exception as erro:  # noqa: BLE001 — vira SystemExit logo abaixo
            print(f"[aviso] Atribuição de clipes falhou ({erro}).")
            bruto, problema = "", f"a chamada falhou ({erro})"
            pareamento = None
        else:
            pareamento = _ler_atribuicao(bruto, topicos, midias)

        if pareamento is None:
            problema = problema or (
                "a resposta não trouxe um clipe DIFERENTE para cada pauta"
            )
        else:
            for k in range(len(topicos)):
                escolha = pareamento[k]
                print(
                    f"[cortes] pauta {k + 1} -> "
                    f"{Path(midias[escolha['midia']]['caminho']).name}: "
                    f"pertinência {escolha['pertinencia']} — {escolha['porque']}"
                )
            fracas = [
                k
                for k in range(len(topicos))
                if pareamento[k]["pertinencia"] < PERTINENCIA_MINIMA
            ]
            if not fracas:
                return [midias[pareamento[k]["midia"]] for k in range(len(topicos))]
            problema = "; ".join(
                f"pauta {k + 1} ('{topicos[k].get('titulo', '')}') ficou com "
                f"{Path(midias[pareamento[k]['midia']]['caminho']).name}, "
                f"pertinência {pareamento[k]['pertinencia']} "
                f"({pareamento[k]['porque']})"
                for k in fracas
            )

        if tentativa >= TENTATIVAS_ATRIBUICAO:
            break
        print(
            f"[cortes] Pareamento reprovado ({tentativa}/"
            f"{TENTATIVAS_ATRIBUICAO}): {problema}"
        )
        mensagens = mensagens + [
            {"role": "assistant", "content": bruto or "{}"},
            {
                "role": "user",
                "content": (
                    "Este pareamento não pode ser publicado: "
                    + problema
                    + f". O piso é {PERTINENCIA_MINIMA}. Refaça o pareamento "
                    "inteiro tentando outros clipes para essas pautas — e se "
                    "nenhum clipe disponível mostrar a coisa de alguma delas, "
                    "mantenha a nota baixa em vez de subi-la: abortar é o "
                    "resultado certo quando o material não tem a imagem."
                ),
            },
        ]

    raise SystemExit(
        "Nenhum pareamento de clipes serve às pautas depois de "
        f"{TENTATIVAS_ATRIBUICAO} tentativas: {problema}.\n"
        f"O piso de pertinência é {PERTINENCIA_MINIMA} (escala 1-5), e uma "
        "pauta cujo clipe não mostra a coisa dela passa dezenas de segundos "
        "com a tela contando outra história. Quando isso acontece, o material "
        "coletado hoje não tem imagem de alguma das pautas — o dia não deu "
        "este vídeo. Abortando sem publicar."
    )
