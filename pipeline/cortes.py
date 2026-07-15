"""Planejamento dos cortes: a IA decide quando cada mídia entra e quanto fica.

O modelo recebe a narração e as mídias disponíveis (com descrições — as dos
posts do X vêm do GPT com visão sobre os arquivos baixados; as da web, da
consulta do roteirista) e devolve a sequência de cortes. Cada corte é ancorado numa
CITAÇÃO EXATA do texto da narração — nunca em segundos, que LLM chuta — e a
citação é convertida em tempo real pelos timestamps por caractere do
alinhamento do ElevenLabs (já remapeados após o corte de silêncios).

Qualquer falha (resposta inválida, citações não encontradas, poucos cortes)
devolve None e o main.py cai no posicionamento automático de sempre.
"""

import json
from pathlib import Path

from openai import OpenAI

from .config import Config

# Mínimo de cortes válidos para aceitar o plano (abaixo disso, fallback)
MIN_CORTES = 2

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

Você recebe o texto da NARRAÇÃO (com duração total) e as MÍDIAS disponíveis
(fotos e clipes de vídeo), cada uma com um id e a descrição do que mostra. As
mídias vêm de duas origens: dos POSTS ORIGINAIS do X sobre o fato (o material
mais autêntico) e de busca na web.

Monte a sequência de cortes: qual mídia aparece, em que ordem e em que momento
da narração cada uma ENTRA. Cada mídia fica na tela até a próxima entrar (a
última vai até o fim). Regras:

1. "entra_em" é uma citação EXATA e CURTA (3 a 8 palavras consecutivas) do
   texto da narração, copiada caractere por caractere, com a mesma pontuação e
   acentuação. NÃO parafraseie: a citação é localizada no texto por busca
   literal, e citação que não existir descarta o corte.
2. O primeiro corte DEVE citar as primeiras palavras da narração — o vídeo
   nunca começa sem mídia.
3. CASE mídia e fala: a mídia entra quando a narração fala do que ela mostra.
   Reserve as mídias dos posts originais para os momentos-chave (gancho e
   clímax).
4. RITMO (estime ~2,5 palavras por segundo): nenhuma mídia fica menos de ~1,5s
   (cortes a menos de 4 palavras um do outro) nem mais de ~8s (~20 palavras).
   Fotos rendem 2 a 4s. Clipe de vídeo bom merece 4 a 8s — não corte um clipe
   no meio da ação (a duração de cada clipe está indicada; clipe mais curto que
   a janela repete em loop).
5. DINÂMICA COM PROGRESSÃO: durações parecidas hipnotizam — os cortes NÃO podem
   ser uniformes. Comece com cortes médios (3–4s) apresentando a situação,
   ACELERE na escalada de fatos (1,5–2,5s por corte) e segure o corte mais
   longo (5–8s) na revelação/clímax, de preferência com a mídia mais forte
   (clipe de vídeo ou a foto-prova). DENSIDADE: mire em um corte a cada 2–4s em
   média — num vídeo de 30–40s, isso significa usar de 8 a 15 mídias. Só fique
   muito abaixo disso se as mídias disponíveis forem realmente fracas.
6. HIERARQUIA DE FORÇA: clipe de vídeo > foto contextualizada (pessoas em ação,
   evento com público, produto em uso) > foto de lugar/retrato > logo, planilha
   ou documento. Mídia fraca (logo em fundo branco, documento, gráfico solto),
   redundante ou fora do assunto: NÃO use (basta omitir) — EXCETO quando o
   documento É a prova da notícia (memo vazado, e-mail da demissão): aí ele
   merece um corte de destaque. Não repita mídia.

Responda somente com o JSON pedido.\
"""


def _rotulo(m: dict) -> str:
    """Linha de apresentação de uma mídia para o modelo."""
    if m.get("dur_s"):
        tipo = f"CLIPE DE VÍDEO de {m['dur_s']:.0f}s"
    elif m.get("tipo") in ("video", "animated_gif"):
        tipo = "CLIPE DE VÍDEO"
    else:
        tipo = "FOTO"
    origem = "post original do X" if m.get("origem") == "x" else "busca na web"
    return f"[{tipo}, {origem}] {m.get('descricao', '').strip()}"


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
    "dur_s": float|None, "origem": "x"|"web"}, ...]. O retorno é compatível com
    `montar_video`: [{"caminho", "inicio_s", "inicio_frac", "fim_frac"}, ...].
    """
    if not midias:
        return None

    listagem = "\n".join(
        f"m{k}: {_rotulo(m)}" for k, m in enumerate(midias, 1)
    )
    conteudo = (
        f"NARRAÇÃO ({dur_total:.0f}s, {len(texto_video.split())} palavras):\n"
        f"{texto_video}\n\n"
        f"MÍDIAS DISPONÍVEIS:\n{listagem}"
    )

    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[cortes] Planejando os cortes de {len(midias)} mídias...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_CORTES},
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
