"""Auditoria do material visual: o que pode e o que não pode entrar no vídeo.

Antes desta camada nada filtrava os clipes: `midia_x` baixava os primeiros que
a X API devolvesse e o planejador de cortes (cortes.py) até era instruído a
omitir clipe fora do assunto — mas, quando ele omitia, o plano caía no
fallback, que usava TODOS os clipes baixados de volta. O caminho do descarte
levava ao uso.

A auditoria roda em duas etapas, sobre um pool maior do que o necessário:

1. VETO DURO, em código: material de telejornal (âncora/repórter/tarja de
   emissora), vinheta de logotipo e qualquer mídia com selo de emissora ou
   veículo de imprensa na imagem sai da disputa. É regra fixa porque o problema
   é recorrente, e julgamento de LLM sobre "isso é jornalismo de terceiro?"
   oscila de execução para execução. Mídia sem laudo de visão também sai —
   material não verificado é justamente o que esta camada existe para barrar.
   NO FORMATO LONGO o telejornal é exceção: em vez de vetado, entra MARCADO
   como representação visual (ver TIPOS_MARCAVEIS).
2. NOTA DE PERTINÊNCIA, com o GPT: cada mídia sobrevivente recebe de 1 a 5
   pela relação entre o que ela MOSTRA e o que a narração DIZ, e abaixo de
   NOTA_MINIMA sai. É aqui que morre o clipe genérico de arquivo que não tem
   nada a ver com o fato narrado.

A etapa 2 falha aberta (aviso no log e todo mundo passa): o veto duro já
resolveu a reclamação principal, e derrubar o vídeo inteiro por um erro
transitório da OpenAI desperdiçaria tudo que foi gasto antes. Já a decisão de
o que fazer quando SOBRA POUCO é de quem chama: `main.py` aborta quando não
sobra clipe nenhum (e, no formato longo, quando sobram menos que o piso).
"""

import json
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Tipos de material barrados por regra, sem passar por julgamento de modelo.
TIPOS_VETADOS = {"reportagem_tv", "logo_ou_marca"}

# No FORMATO LONGO o material de telejornal deixa de ser vetado: entra MARCADO
# como representação visual (dessaturado + etiqueta na tela, ver edicao.py).
# 90-120s de tela raramente se sustentam só com cena crua, e a marcação resolve
# o que originou o veto — o espectador tomar cobertura de terceiro por material
# do canal. O selo de emissora acompanha: barrá-lo derrubaria justamente os
# clipes de telejornal que a marcação existe para admitir. Já 'logo_ou_marca'
# segue vetado nos dois formatos — vinheta de logotipo não representa assunto
# nenhum, não há o que marcar. A nota de pertinência continua valendo para
# todo mundo, então telejornal que não mostra o fato narrado cai nela.
TIPOS_MARCAVEIS = {"reportagem_tv"}

NOTA_MINIMA = 3  # abaixo disto a mídia não entra no vídeo

ESQUEMA_AUDITORIA = {
    "name": "auditoria_de_midias",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vereditos": {
                "type": "array",
                "description": "Um veredito para CADA mídia recebida.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "midia": {
                            "type": "string",
                            "description": "id da mídia julgada (ex.: m3)",
                        },
                        "nota": {
                            "type": "integer",
                            "description": (
                                "1 a 5: o quanto o que a mídia MOSTRA é o que a "
                                "narração DIZ."
                            ),
                        },
                        "motivo": {
                            "type": "string",
                            "description": (
                                "Uma frase curta justificando a nota, citando o "
                                "que a mídia mostra."
                            ),
                        },
                    },
                    "required": ["midia", "nota", "motivo"],
                },
            },
        },
        "required": ["vereditos"],
    },
}

INSTRUCOES_AUDITORIA = """\
Você é o AUDITOR DE MATERIAL VISUAL de um canal de vídeos jornalísticos. Você
recebe a NARRAÇÃO de um vídeo e a descrição de cada mídia candidata a aparecer
na tela, e dá a cada uma uma nota de 1 a 5.

A nota mede UMA coisa só: o quanto aquilo que a mídia MOSTRA é aquilo que a
narração DIZ. Não julgue beleza, qualidade de imagem nem importância do tema.

ESCALA:
5 = mostra exatamente o fato, a pessoa, o lugar, o equipamento ou o produto de
    que a narração fala.
4 = mostra o contexto direto do fato (a mesma empresa, o mesmo país, a mesma
    tecnologia), ainda que em outro momento.
3 = relacionado de forma reconhecível; serve de apoio sem enganar o espectador.
2 = genérico ou de arquivo: só decora, poderia ilustrar qualquer outra notícia.
1 = é outro assunto.

REGRAS DE TETO (a nota NÃO pode passar disso):
- Mídia que só mostra a MANCHETE, o print ou a cartela de um veículo de
  imprensa em vez de mostrar o fato: no máximo 2. O canal mostra o
  acontecimento, não a cobertura que os outros fizeram dele.
- Mídia cujo texto na tela contradiz a narração (outro número, outra pessoa,
  outra data): no máximo 2.
- Mídia em que não dá para saber o que está sendo mostrado: no máximo 2.

Seja rigoroso: é melhor o vídeo ficar com menos material do que mostrar na tela
uma coisa enquanto a narração fala de outra. Dê um veredito para CADA mídia
recebida, usando o id exato dela. Responda somente com o JSON pedido.\
"""


def _rotulo_midia(m: dict, laudo: dict) -> str:
    """Linha de apresentação de uma mídia para o auditor."""
    partes = [f"tipo: {laudo.get('tipo_material', '?')}"]
    if m.get("dur_s"):
        partes.append(f"{m['dur_s']:.0f}s de vídeo")
    if m.get("conta"):
        partes.append(f"post de {m['conta']}")
    linha = f"[{', '.join(partes)}] {(laudo.get('descricao') or '').strip()}"
    if (laudo.get("texto_na_tela") or "").strip():
        linha += f"\n    Texto na tela: \"{laudo['texto_na_tela'].strip()}\""
    return linha


def _motivo_do_veto(laudo: dict, marcar_tv: bool) -> tuple[str, bool]:
    """(motivo do veto, marcar como representação visual).

    Motivo vazio = a mídia segue para a nota de pertinência. Com `marcar_tv`
    (formato longo), telejornal e selo de emissora não vetam mais: a mídia
    passa marcada, e a marcação vira dessaturação + etiqueta na montagem.
    """
    tipo = laudo.get("tipo_material", "")
    marcada = False
    if tipo in TIPOS_VETADOS:
        if not (marcar_tv and tipo in TIPOS_MARCAVEIS):
            return f"material do tipo '{tipo}' (veto duro)", False
        marcada = True
    if laudo.get("selo_de_emissora"):
        if not marcar_tv:
            marca = (laudo.get("marca_visivel") or "").strip()
            return (
                "selo de emissora/veículo na imagem"
                f"{f' ({marca})' if marca else ''}",
                False,
            )
        marcada = True
    return "", marcada


def _notas(
    cfg: Config, texto_video: str, candidatas: list[dict]
) -> dict[int, tuple[int, str]]:
    """Nota de pertinência de cada candidata; {índice: (nota, motivo)}.

    Falha aberta: erro na chamada devolve dicionário vazio e quem chama trata
    a ausência de nota como aprovação (o veto duro já rodou).
    """
    listagem = "\n".join(
        f"m{k}: {_rotulo_midia(m, m['laudo'])}"
        for k, m in enumerate(candidatas, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO:\n{texto_video}\n\n"
        f"MÍDIAS CANDIDATAS:\n{listagem}"
    )
    cliente = OpenAI(api_key=cfg.openai_api_key)
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_AUDITORIA},
                {"role": "user", "content": conteudo},
            ],
            response_format={
                "type": "json_schema", "json_schema": ESQUEMA_AUDITORIA
            },
        )
        vereditos = json.loads(resposta.choices[0].message.content)["vereditos"]
    except Exception as erro:  # noqa: BLE001 — falha aberta, ver docstring
        print(
            f"[aviso] Auditoria de pertinência falhou ({erro}); seguindo só "
            "com o veto duro de tipo de material."
        )
        return {}

    notas: dict[int, tuple[int, str]] = {}
    for v in vereditos:
        bruto = str(v.get("midia", "")).strip().lstrip("m")
        try:
            indice = int(bruto) - 1
        except ValueError:
            continue
        if 0 <= indice < len(candidatas):
            nota = max(1, min(5, int(v.get("nota", 0) or 0)))
            notas[indice] = (nota, (v.get("motivo") or "").strip())
    return notas


def auditar_midias(
    cfg: Config,
    texto_video: str,
    midias: list[dict],
    laudos: dict[str, dict],
    limite: int,
    rotulo: str = "clipe",
    pasta: Path | None = None,
) -> list[dict]:
    """Aprova até `limite` mídias, da mais pertinente para a menos.

    `laudos` vem de `midia_x.descrever_midias` (visão estruturada). Cada mídia
    aprovada volta com "descricao", "tipo_material", "nota" e "motivo"
    preenchidos. A ordem importa: quem chama usa a lista como está quando o
    planejador de cortes falha, e nesse caso o primeiro item abre o vídeo —
    então a melhor mídia vem primeiro.

    Com `pasta`, grava `auditoria_{rotulo}.json` com aprovadas e reprovadas
    para dar rastro do que foi barrado e por quê.
    """
    if not midias:
        return []

    marcar_tv = getattr(cfg, "formato", "curto") == "longo"

    candidatas: list[dict] = []
    reprovadas: list[dict] = []
    for m in midias:
        laudo = laudos.get(str(m["caminho"]))
        if not laudo:
            reprovadas.append(dict(m, motivo="sem laudo de visão"))
            continue
        veto, marcada = _motivo_do_veto(laudo, marcar_tv)
        if veto:
            reprovadas.append(dict(m, laudo=laudo, motivo=veto))
            continue
        candidatas.append(dict(m, laudo=laudo, representacao=marcada))

    notas = _notas(cfg, texto_video, candidatas) if candidatas else {}

    aprovadas: list[dict] = []
    for i, m in enumerate(candidatas):
        # Sem nota (auditoria de pertinência falhou) a mídia passa com o valor
        # neutro: o veto duro já rodou e é ele que carrega a regra do canal.
        nota, motivo = notas.get(i, (NOTA_MINIMA, "sem nota de pertinência"))
        item = dict(
            m,
            descricao=(m["laudo"].get("descricao") or "").strip(),
            tipo_material=m["laudo"].get("tipo_material", ""),
            nota=nota,
            motivo=motivo,
        )
        item.pop("laudo", None)
        if nota < NOTA_MINIMA:
            reprovadas.append(item)
        else:
            aprovadas.append(item)

    aprovadas.sort(key=lambda m: -m["nota"])
    excedentes = aprovadas[limite:]
    aprovadas = aprovadas[:limite]

    for m in reprovadas:
        print(
            f"[auditoria] REPROVADO {Path(m['caminho']).name}: "
            f"{m.get('motivo') or '?'}"
        )
    for m in excedentes:
        print(
            f"[auditoria] sobra (fora do teto de {limite}) "
            f"{Path(m['caminho']).name}: nota {m['nota']}"
        )
    for m in aprovadas:
        marca = " [marcado: representação visual]" if m.get("representacao") else ""
        print(
            f"[auditoria] ok {Path(m['caminho']).name}: nota {m['nota']} "
            f"({m['tipo_material']}){marca} — {m['motivo']}"
        )
    print(
        f"[auditoria] {len(aprovadas)} {rotulo}(s) aprovado(s) de "
        f"{len(midias)} candidato(s)"
    )

    if pasta is not None:
        registro = {
            "aprovadas": [
                {
                    "arquivo": Path(m["caminho"]).name,
                    "nota": m["nota"],
                    "tipo_material": m["tipo_material"],
                    "representacao_visual": bool(m.get("representacao")),
                    "motivo": m["motivo"],
                }
                for m in aprovadas
            ],
            "reprovadas": [
                {
                    "arquivo": Path(m["caminho"]).name,
                    "motivo": m.get("motivo", ""),
                    "nota": m.get("nota"),
                }
                for m in reprovadas + excedentes
            ],
        }
        (pasta / f"auditoria_{rotulo}.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return aprovadas
