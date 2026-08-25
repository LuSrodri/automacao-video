"""Triagem do material visual ANTES de escolher a trend.

O pipeline escolhia a pauta às cegas quanto a imagem: a seleção via quantos
posts da candidata tinham clipe, mas não o que esses clipes MOSTRAVAM. Só
depois de escrever o roteiro, baixar o material e pagar a visão é que a
auditoria descobria que o único clipe era um busto falante — e aí a tentativa
inteira ia embora. Em 2026-08-17 e 18 isso se repetiu três vezes por execução,
noite adentro.

Esta camada inverte a ordem (pedido do usuário em 2026-08-18: "na hora de
escolher a trend, tem que já ver se os vídeos são bons"). Ela baixa UM clipe de
cada candidata, roda a mesma visão da auditoria e devolve o veredito para dentro
da trend, de modo que a seleção escolha sabendo quem tem imagem aproveitável.

Custo e limites, de propósito:

- um clipe por candidata, e no máximo `MAX_CANDIDATAS` candidatas;
- o clipe baixado é REAPROVEITADO no laudo da auditoria (mesmo caminho de
  arquivo), então a visão não é paga duas vezes pelo mesmo material;
- falha aqui não derruba nada: candidata sem veredito entra na disputa como
  entrava antes, e a auditoria segue sendo a palavra final.
"""

from pathlib import Path

from .auditoria import _motivo_do_veto
from .config import Config
from .midia_x import baixar_midias_posts, descrever_midias

# Teto de candidatas triadas por execução. As trends chegam ordenadas por valor
# informativo, então as de baixo raramente são escolhidas — triá-las seria pagar
# download e visão por uma decisão que não muda.
MAX_CANDIDATAS = 6


def triar_material(cfg: Config, trends: list[dict], pasta: Path) -> None:
    """Anota em cada trend se o material dela sobrevive ao veto. Muta a lista.

    Escreve dois campos na trend:

    - ``clipe_aprovado``: True/False quando houve veredito, None quando não deu
      para julgar (sem clipe baixado, visão falhou, candidata fora do teto).
    - ``clipe_motivo``: o motivo do veto, para o log e para o prompt de seleção.
    """
    candidatas = [t for t in trends if t.get("posts_com_video")][:MAX_CANDIDATAS]
    if not candidatas:
        return

    print(
        f"[triagem] Conferindo o material de {len(candidatas)} candidata(s) "
        "antes da escolha (1 clipe cada)..."
    )
    pasta.mkdir(parents=True, exist_ok=True)
    for i, trend in enumerate(candidatas, 1):
        destino = pasta / f"triagem_{i}"
        destino.mkdir(exist_ok=True)
        # Um clipe só: é amostra, não é o pool do vídeo.
        cfg_amostra = _com_teto_de_um(cfg)
        try:
            clipes, _ = baixar_midias_posts(
                cfg_amostra, (trend.get("posts") or [])[:2], destino
            )
        except SystemExit:
            raise
        except Exception as erro:  # download é rede: não derruba a execução
            print(f"[triagem] {trend['trend'][:40]}: falha no download ({erro})")
            continue
        if not clipes:
            continue

        laudos = descrever_midias(cfg_amostra, clipes[:1])
        laudo = laudos.get(str(clipes[0]["caminho"]))
        if not laudo:
            continue

        # Os mesmos vetos duros da auditoria, na mesma ordem: o que a amostra
        # reprova aqui a candidata inteira perderia depois, com o roteiro já
        # escrito e a visão já paga.
        veto, _ = _motivo_do_veto(laudo, cfg.formato == "longo", True, True)
        trend["clipe_aprovado"] = not veto
        trend["clipe_motivo"] = veto
        # O arquivo fica: se esta trend for a escolhida, a auditoria reusa o
        # clipe já baixado em vez de pagar o download de novo.
        trend["clipe_triado"] = str(clipes[0]["caminho"])
        marca = "OK" if not veto else f"VETADO ({veto[:48]})"
        print(f"[triagem]   {marca}: {trend['trend'][:52]}")

    aprovadas = sum(1 for t in candidatas if t.get("clipe_aprovado"))
    print(
        f"[triagem] {aprovadas} de {len(candidatas)} candidata(s) com clipe "
        "aprovável; a seleção decide sabendo disso."
    )


def _com_teto_de_um(cfg: Config) -> Config:
    """Cópia do Config que baixa UM clipe e nenhuma foto (amostra barata)."""
    from copy import copy

    amostra = copy(cfg)
    amostra.max_clipes = 1
    amostra.pool_extra_clipes = 0
    amostra.max_fotos = 0
    amostra.max_posts_midia = 2
    return amostra
