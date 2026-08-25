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
último vai até o fim; clipe mais curto que a janela repete em loop). Regras:

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
4. RITMO (estime ~2,5 palavras por segundo): nenhum clipe fica menos de ~3s na
   tela, e as janelas NÃO precisam ser iguais — clipe forte segura 8 a 15s,
   clipe de apoio resolve em 3 a 6s. Se possível, troque de clipe perto da
   virada da narração (fato → implicação) para renovar a atenção.
5. Clipe fora do assunto, redundante ou que só mostra logomarca: NÃO use
   (basta omitir — com 1 clipe bom o vídeo inteiro pode ficar nele). Não
   repita clipe.

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
    """Linha de apresentação de um clipe para o modelo."""
    if m.get("dur_s"):
        tipo = f"CLIPE DE VÍDEO de {m['dur_s']:.0f}s"
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
# deixou de ser usado: lá o vídeo virou quatro partes fechadas
# (montagem_longa.py) e a pergunta mudou de "em que segundo cada clipe entra"
# para "qual clipe é o da pauta 1, qual é o da 2 e qual é o da 3".
#
# O usuário foi explícito: "para cada pauta, é obrigatório o vídeo. Um mesmo
# vídeo não pode servir para duas pautas." Por citação isso nunca teve garantia
# — o modelo casava o clipe com o trecho e o mesmo arquivo atravessava duas
# pautas —, então a atribuição virou um problema de PAREAMENTO, com o resultado
# conferido em código: três pautas, três arquivos, todos diferentes.

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
                    },
                    "required": ["pauta", "midia", "porque"],
                },
            },
        },
        "required": ["pautas"],
    },
}

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

Responda somente com o JSON pedido.\
"""


def _atribuicao_de_reserva(topicos: list[dict], midias: list[dict]) -> list[int]:
    """Pareamento sem o modelo: o clipe mais longo para a pauta mais longa.

    Reserva para quando a chamada falha ou volta inútil. Não sabe nada sobre o
    ASSUNTO — mas cumpre as duas regras duras (toda pauta tem clipe, nenhum
    repete), que é o que a montagem exige para existir. Ordem por duração
    porque é o único sinal de qualidade disponível aqui: clipe de dois segundos
    em loop numa pauta de quarenta é o pior resultado possível.
    """
    ordem = sorted(
        range(len(midias)),
        key=lambda k: (midias[k].get("dur_s") or 0.0),
        reverse=True,
    )
    return ordem[: len(topicos)]


def atribuir_clipes(
    cfg: Config, roteiro: dict, midias: list[dict]
) -> list[dict]:
    """Devolve UM clipe por pauta do roteiro, sem repetir nenhum.

    `midias`: [{"caminho": Path, "descricao": str, "dur_s": float|None,
    "conta": str, ...}, ...] — os clipes já aprovados pela auditoria. O retorno
    é a lista de mídias na ordem das pautas, com os campos originais
    preservados.

    Levanta SystemExit se não houver clipe para todas as pautas: é a regra que
    o usuário pediu, e um vídeo em que duas pautas mostram o mesmo material é
    exatamente o que ele rejeitou.
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

    escolhas: list[int] = []
    print(f"[cortes] Casando {len(midias)} clipe(s) com {len(topicos)} pauta(s)...")
    try:
        cliente = OpenAI(api_key=cfg.openai_api_key)
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_ATRIBUICAO},
                {"role": "user", "content": conteudo},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_ATRIBUICAO,
            },
        )
        dados = json.loads(resposta.choices[0].message.content)["pautas"]
        por_pauta: dict[int, int] = {}
        vistos: set[int] = set()
        for item in dados:
            try:
                pauta = int(item.get("pauta", 0)) - 1
                indice = int(str(item.get("midia", "")).strip().lstrip("m")) - 1
            except ValueError:
                continue
            # Repetição é descartada em vez de aceita: a regra é do usuário, e
            # deixar passar aqui derrubaria a montagem lá na frente.
            if not (0 <= pauta < len(topicos) and 0 <= indice < len(midias)):
                continue
            if pauta in por_pauta or indice in vistos:
                continue
            por_pauta[pauta] = indice
            vistos.add(indice)
            print(
                f"[cortes] pauta {pauta + 1} -> "
                f"{Path(midias[indice]['caminho']).name}: "
                f"{item.get('porque', '')}"
            )
        if len(por_pauta) == len(topicos):
            escolhas = [por_pauta[k] for k in range(len(topicos))]
    except Exception as erro:  # noqa: BLE001 — há reserva para tudo aqui
        print(f"[aviso] Atribuição de clipes falhou ({erro}); usando a reserva.")

    if not escolhas:
        escolhas = _atribuicao_de_reserva(topicos, midias)
        print(
            "[cortes] Pareamento de reserva (por duração): "
            + ", ".join(
                f"pauta {k + 1} -> {Path(midias[i]['caminho']).name}"
                for k, i in enumerate(escolhas)
            )
        )
    return [midias[i] for i in escolhas]
