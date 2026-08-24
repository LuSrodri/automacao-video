"""Manchetes do formato longo: o texto que dá ritmo e divisão ao vídeo.

O problema (2026-08-23, diagnóstico do usuário): o vídeo longo é MONÓTONO. Ele
tem 135 segundos de narração corrida sobre clipes que trocam, sem nenhuma marca
de que a pauta mudou — o espectador não sabe onde está, não sabe o que ainda
vem, e não tem por que ficar.

Esta camada resolve isso com duas peças, ambas ancoradas em CITAÇÕES LITERAIS
da narração (o mesmo mecanismo das cartelas e dos capítulos — o
único jeito de o texto na tela cair no segundo em que a narração diz aquilo):

1. AINDA NESTE VÍDEO — no canto inferior esquerdo, ACOMPANHANDO a pauta que a
   narração está dizendo em voz alta nos primeiros ~6 segundos (campo
   `pauta_falada` do roteiro): os títulos entram um a um enquanto a fala os
   nomeia. Na primeira versão (23/08) o índice subia DEPOIS da pergunta de
   abertura e listava tópicos que a narração não mencionava — a tela dizia uma
   coisa e o áudio dizia outra, que é a "confusão" que o usuário relatou em
   24/08. Sem a pauta falada localizada no texto, o índice não sai.
2. UMA MANCHETE POR PAUTA — quando a pauta vira, a manchete daquela pauta entra
   no mesmo canto, DENTRO da pausa de silêncio que o pipeline abriu logo antes
   da frase de virada (silencio.inserir_pausas). O espectador ouve o silêncio,
   lê o título novo e só então a narração recomeça: é a separação temporal e
   visual pedida em 24/08, e é o que transforma um bloco corrido em capítulos
   que o espectador percebe.

ESTILO — o MESMO da capa (identidade.py), a pedido do usuário depois de a capa
ficar boa: etiqueta de cor chapada com retícula Ben-Day, título em grotesca
pesada com a desregistragem ciano/magenta e um grifo à mão por baixo. A tarja
fininha lateral da primeira versão saiu — ela lia como enfeite de template, não
como a marca do canal. O MOVIMENTO
é do ffmpeg (edicao.py): a manchete entra deslizando da borda esquerda com
aceleração suave e sai pelo mesmo caminho. Aqui só se renderiza o painel
parado, do tamanho exato do seu conteúdo — e não da largura do quadro, porque
um PNG de faixa inteira multiplicaria a memória do overlay num formato que já
estourou o container.

Só o formato LONGO usa esta camada: o Short tem legenda queimada ocupando a
tela e 25 segundos que não comportam índice nenhum.

Etapa opcional: qualquer falha (fonte ausente, Pillow, citação não encontrada)
só deixa o vídeo sem manchetes — nunca derruba o pipeline.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

from . import identidade as ident
from .config import Config
from .cortes import _tempo_do_char

# --- Rótulos por canal -------------------------------------------------------
# Idioma é regra de CANAL (config.IDIOMA_CANAL), nunca inferido: texto na tela é
# texto do canal como qualquer outro.
RUBRICAS = {
    "brasil": "AINDA NESTE VÍDEO",
    "usa": "COMING UP",
}

# --- Tempo -------------------------------------------------------------------
# O índice acompanha a PAUTA FALADA, que o roteiro entrega em no máximo 18
# palavras (~6s). O teto existe como guarda: se a fala escorregar, o índice não
# invade o corpo do vídeo.
ABERTURA_MAX_S = 6.5
ABERTURA_ITEM_MIN_S = 1.4  # abaixo disso não dá tempo de ler o tópico
DUR_MANCHETE = 4.2  # tempo-alvo da manchete de um tópico na tela
DUR_MINIMA = 2.0
GAP = 0.7  # respiro entre uma peça e a seguinte
# Piso de segurança para a manchete de um tópico: nada de painel de pauta em
# cima da abertura. O ÍNDICE não obedece a isto — ele é a abertura.
INICIO_MINIMO = 3.0

# --- Geometria (frações do quadro) -------------------------------------------
MARGEM_X_FRAC = 0.052
# Base do painel. Fica ACIMA da etiqueta de REPRESENTAÇÃO VISUAL (edicao.py,
# REPR_Y_FRAC = 0.912), que é marcação obrigatória de material de terceiro e
# não pode ser coberta.
BASE_FRAC = 0.880
LARGURA_MAX_FRAC = 0.62
TITULO_FRAC = 0.050  # tamanho da fonte do título, fração da altura do quadro
KICKER_FRAC = 0.020
PAD_FRAC = 0.020
FUNDO_ALFA = 232
ENTRELINHA = 1.14
TRACKING_FRAC = 0.34  # espaçamento do kicker, fração do tamanho da fonte


def _medidor() -> ImageDraw.ImageDraw:
    """Um Draw descartável só para medir texto antes de criar a tela real."""
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


def _painel(
    titulo: str,
    kicker: str,
    destino: Path,
    altura_quadro: int,
    largura_max: int,
    cor: tuple,
    contador: str = "",
    altura_minima: int = 0,
) -> tuple[Path, int, int]:
    """Renderiza um painel de manchete; devolve (caminho, largura, altura).

    O PNG tem o tamanho do CONTEÚDO — não a largura do quadro. Um PNG de faixa
    inteira custaria memória de overlay em cada frame da janela sem desenhar
    nada nas bordas, e este é um formato que já estourou o container.

    `altura_minima` iguala a altura de todos os painéis do vídeo. Sem isso, um
    título que quebra em duas linhas gera um painel mais alto que o do vizinho,
    e a lista da abertura sobe e desce a cada item — o painel é ancorado pela
    BASE, então altura variável vira solavanco. Com a altura fixa, o título
    ganha o espaço que sobra centrado abaixo do fio.
    """
    medidor = _medidor()
    pad = round(altura_quadro * PAD_FRAC)
    tam_kicker = max(11, round(altura_quadro * KICKER_FRAC))
    f_kicker = ident.fonte(tam_kicker)
    # O tracking largo é o que faz uma linha pequena ler como RÓTULO. Num
    # kicker de duas letras ("02") ele só afasta os dois algarismos e o número
    # deixa de ser um número: aí o espaçamento sai.
    tracking = tam_kicker * TRACKING_FRAC if len(kicker) > 3 else 0.0

    util_max = largura_max - 2 * pad
    f_titulo, linhas = ident.caber(
        medidor, titulo.upper(), util_max, round(altura_quadro * TITULO_FRAC),
        minimo=max(16, round(altura_quadro * 0.028)), maximo_linhas=2,
    )
    larg_titulo = max(
        (medidor.textlength(linha, font=f_titulo) for linha in linhas), default=0
    )

    # ETIQUETA: o mesmo bloco de cor chapado que na capa envolve a palavra do
    # fato (identidade.etiqueta). Ela fica ACIMA do slab, encostada à esquerda,
    # e é o que dá cor à peça — a tarja fininha lateral que existia antes lia
    # como enfeite de template, não como a marca do canal.
    pad_et = max(4, round(tam_kicker * 0.45))
    larg_rotulo = ident.largura_espacada(medidor, kicker, f_kicker, tracking)
    if contador:
        larg_rotulo += pad_et * 2 + medidor.textlength(contador, font=f_kicker)
    larg_etiqueta = round(larg_rotulo + 2 * pad_et)
    alt_etiqueta = round(tam_kicker + 2 * pad_et)

    alt_linha = round(f_titulo.size * ENTRELINHA)
    largura = round(max(larg_etiqueta, min(util_max, larg_titulo) + 2 * pad))
    alt_slab = round(2 * pad + alt_linha * len(linhas))
    alt_conteudo = alt_etiqueta + alt_slab
    altura = max(alt_conteudo, int(altura_minima))
    # A etiqueta fica colada no topo; a folga da altura uniforme cai no slab,
    # com o título centrado nela.
    sobra = altura - alt_conteudo

    tela = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr = ImageDraw.Draw(tela, "RGBA")

    topo_slab = alt_etiqueta
    dr.rectangle([0, topo_slab, largura, altura], fill=(*ident.PRETO, FUNDO_ALFA))
    # Retícula bem fraca no corpo do slab: a textura de impressão que liga a
    # manchete à capa, sem virar ruído atrás do texto.
    ident.reticula(
        tela, (0, topo_slab, largura, altura), cor=ident.BRANCO,
        passo=max(9, round(altura_quadro * 0.012)), raio=1, alfa=20,
    )

    ident.etiqueta(
        tela, (0, 0, larg_etiqueta, alt_etiqueta), cor,
        passo_reticula=max(6, round(tam_kicker * 0.42)),
    )
    ident.escrever_espacado(
        dr, (pad_et, pad_et), kicker, f_kicker, ident.PRETO, tracking
    )
    if contador:
        dr.text(
            (larg_etiqueta - pad_et, pad_et), contador, font=f_kicker,
            fill=(*ident.PRETO, 170), anchor="ra",
        )

    y = topo_slab + pad + sobra // 2
    for i, linha in enumerate(linhas):
        ident.escrever_cromatico(tela, (pad, y), linha, f_titulo, ident.BRANCO)
        if i == len(linhas) - 1:
            # Grifo à mão sob a última linha: o traço da capa, reduzido.
            larg_linha = medidor.textlength(linha, font=f_titulo)
            # 1,10 do corpo da fonte deixa o traço ABAIXO das maiúsculas do
            # Archivo Black; em 1,02 ele cortava o pé das letras.
            ident.risco_a_mao(
                tela, pad, pad + larg_linha, y + f_titulo.size * 1.10, cor,
                largura=max(3, round(f_titulo.size * 0.085)),
                sem=ident.semente(titulo),
            )
        y += alt_linha

    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino, largura, altura


def _tempo_da_citacao(
    texto_baixo: str, texto_video: str, alinhamento: dict, dur_total: float,
    citacao: str,
) -> float | None:
    trecho = " ".join((citacao or "").split()).lower()
    if not trecho:
        return None
    pos = texto_baixo.find(trecho)
    if pos < 0:
        return None
    return _tempo_do_char(alinhamento, texto_video, pos, dur_total)


def _marcos_dos_topicos(
    topicos: list[dict], texto_video: str, alinhamento: dict, dur_total: float
) -> list[tuple[float, str]]:
    """(instante, título) de cada tópico que tem âncora real na narração."""
    texto_baixo = texto_video.lower()
    marcos: list[tuple[float, str]] = []
    for topico in topicos:
        titulo = " ".join((topico.get("titulo") or "").split())
        if not titulo:
            continue
        inicio = _tempo_da_citacao(
            texto_baixo, texto_video, alinhamento, dur_total,
            topico.get("citacao") or "",
        )
        if inicio is None:
            print(
                f"[manchetes] Tópico sem âncora na narração, sem manchete: "
                f"{titulo}"
            )
            continue
        if inicio < INICIO_MINIMO:
            print(
                f"[manchetes] '{titulo}' cai em {inicio:.1f}s, dentro do "
                f"gancho (< {INICIO_MINIMO:.0f}s); sem manchete."
            )
            continue
        marcos.append((inicio, titulo))
    marcos.sort(key=lambda m: m[0])
    return marcos


def _janela_da_pauta_falada(
    roteiro: dict, texto_video: str, alinhamento: dict, dur_total: float
) -> tuple[float, float]:
    """(início, fim) do trecho em que a narração DIZ a pauta do vídeo.

    O índice na tela existe para acompanhar essa fala — os títulos aparecem
    enquanto a narração os nomeia (2026-08-24, pedido do usuário). Antes o
    índice subia depois da pergunta de abertura e listava tópicos que a
    narração não mencionava: a tela dizia uma coisa e o áudio dizia outra, que
    foi exatamente a "confusão" relatada.

    Sem conseguir localizar a pauta falada no texto (modelo que não copiou o
    campo caractere por caractere), devolve uma janela vazia e o índice não
    sai — índice fora de sincronia com a fala é pior que índice nenhum.
    """
    pauta = " ".join((roteiro.get("pauta_falada") or "").split())
    if not pauta:
        return 0.0, 0.0
    pos = texto_video.lower().find(pauta.lower())
    if pos < 0:
        print(
            "[manchetes] A pauta falada não foi encontrada na narração "
            "(o modelo não copiou o campo); vídeo sem índice de abertura."
        )
        return 0.0, 0.0
    inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
    fim_char = min(pos + len(pauta), len(texto_video) - 1)
    fim = _tempo_do_char(alinhamento, texto_video, fim_char, dur_total)
    return inicio, min(fim, inicio + ABERTURA_MAX_S)


def gerar_manchetes(
    cfg: Config,
    roteiro: dict,
    texto_video: str,
    alinhamento: dict,
    dur_total: float,
    pasta: Path,
    tela: tuple[int, int],
) -> list[dict]:
    """Monta as manchetes do vídeo longo; devolve a lista para `montar_video`.

    Retorno: [{"imagem": str, "inicio_s": float, "dur_s": float, "x": int,
    "y": int}, ...] — a posição é o canto superior esquerdo do painel em
    repouso; o deslize até lá é do ffmpeg. Lista vazia quando o formato não usa
    manchetes, quando nenhum tópico tem âncora ou quando qualquer etapa falha.
    """
    if not cfg.manchetes or cfg.formato != "longo":
        return []
    if not ident.fonte_disponivel():
        print("[manchetes] Fonte Archivo Black ausente; vídeo sem manchetes.")
        return []

    topicos = roteiro.get("topicos") or []
    if not topicos:
        print("[manchetes] Roteiro sem tópicos; vídeo sem manchetes.")
        return []

    try:
        largura_quadro, altura_quadro = tela
        margem_x = round(largura_quadro * MARGEM_X_FRAC)
        largura_max = round(largura_quadro * LARGURA_MAX_FRAC)
        base = round(altura_quadro * BASE_FRAC)
        cor = ident.DESTAQUES[0]  # uma cor por canal, estável em todo o vídeo
        rubrica = RUBRICAS.get(cfg.publico, RUBRICAS["brasil"])

        marcos = _marcos_dos_topicos(topicos, texto_video, alinhamento, dur_total)

        # Os painéis são montados em duas etapas: primeiro a LISTA do que vai
        # entrar (com tempo e texto), e só depois o desenho — a altura de todos
        # precisa ser a mesma, e ela só se conhece depois de medir o mais alto.
        pedidos: list[dict] = []

        def _acrescentar(
            nome: str, titulo: str, kicker: str, inicio: float, dur: float,
            contador: str = "",
        ) -> None:
            pedidos.append(
                {
                    "nome": nome, "titulo": titulo, "kicker": kicker,
                    "contador": contador,
                    "inicio_s": round(inicio, 3), "dur_s": round(dur, 3),
                }
            )

        # --- 1. AINDA NESTE VÍDEO: o índice ACOMPANHA a pauta falada --------
        inicio_indice, fim_indice = _janela_da_pauta_falada(
            roteiro, texto_video, alinhamento, dur_total
        )
        # O índice tem que ACABAR antes de a primeira pauta entrar: ele promete
        # o que vem, e prometer por cima do primeiro tópico já entregue é ruído.
        limite = marcos[0][0] - GAP if marcos else dur_total * 0.45
        disponivel = min(fim_indice, limite) - inicio_indice
        itens = [" ".join((t.get("titulo") or "").split()) for t in topicos]
        itens = [i for i in itens if i]
        cabem = int(disponivel // ABERTURA_ITEM_MIN_S) if disponivel > 0 else 0
        if cabem >= 2 and itens:
            itens = itens[: min(len(itens), cabem)]
            passo = disponivel / len(itens)
            for k, item in enumerate(itens):
                _acrescentar(
                    f"manchete_indice_{k + 1}.png", item, rubrica,
                    inicio_indice + k * passo, passo,
                    contador=f"{k + 1}/{len(itens)}",
                )
            print(
                f"[manchetes] '{rubrica}' de {inicio_indice:.1f}s a "
                f"{inicio_indice + disponivel:.1f}s, {len(itens)} tópico(s)."
            )
        else:
            print(
                "[manchetes] Sem janela para o índice de abertura "
                f"({max(disponivel, 0):.1f}s até a primeira pauta); pulado."
            )

        # --- 2. Uma manchete por pauta --------------------------------------
        # A manchete entra DENTRO da pausa de silêncio que o pipeline abriu
        # logo antes da frase de virada (silencio.inserir_pausas): o espectador
        # ouve o silêncio, lê o título novo, e só então a narração recomeça. Sem
        # recuar pela pausa, o painel entraria junto com a primeira palavra e a
        # separação temporal não teria contrapartida na tela.
        pausa = max(0.0, float(getattr(cfg, "pausa_pauta_s", 0.0) or 0.0))
        for k, (marco, titulo) in enumerate(marcos, 1):
            inicio = max(0.0, marco - pausa)
            proximo = marcos[k][0] - pausa if k < len(marcos) else dur_total
            dur = min(DUR_MANCHETE, proximo - GAP - inicio, dur_total - 0.4 - inicio)
            if dur < DUR_MINIMA:
                print(
                    f"[manchetes] '{titulo}' teria só {max(dur, 0):.1f}s na "
                    "tela; descartada."
                )
                continue
            _acrescentar(f"manchete_topico_{k}.png", titulo, f"{k:02d}", inicio, dur)
            print(f"[manchetes] {k:02d} '{titulo}' @ {inicio:.1f}s por {dur:.1f}s")

        if not pedidos:
            return []

        # Desenho: primeira passada mede, segunda iguala a altura de todos.
        def _desenhar(altura_minima: int) -> list[tuple[Path, int, int]]:
            return [
                _painel(
                    pedido["titulo"], pedido["kicker"], pasta / pedido["nome"],
                    altura_quadro, largura_max, cor, pedido["contador"],
                    altura_minima,
                )
                for pedido in pedidos
            ]

        desenhos = _desenhar(0)
        alvo = max(alt for _, _, alt in desenhos)
        if any(alt != alvo for _, _, alt in desenhos):
            desenhos = _desenhar(alvo)

        plano: list[dict] = []
        registro: list[dict] = []
        for pedido, (caminho, larg, alt) in zip(pedidos, desenhos):
            item = {
                "imagem": str(caminho),
                "inicio_s": pedido["inicio_s"],
                "dur_s": pedido["dur_s"],
                "x": margem_x,
                "y": max(0, base - alt),
                "largura": larg,
                "altura": alt,
            }
            plano.append(item)
            registro.append(
                dict(item, kicker=pedido["kicker"], titulo=pedido["titulo"])
            )
    except Exception as erro:  # noqa: BLE001 — manchete nunca derruba o vídeo
        print(f"[aviso] Manchetes falharam ({erro}); seguindo sem elas.")
        return []

    if registro:
        (pasta / "manchetes.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return plano


def instantes_das_viradas(
    roteiro: dict,
    texto_video: str,
    alinhamento: dict,
    dur_total: float,
) -> list[float]:
    """Instantes em que uma pauta começa — onde o silêncio deve ser aberto.

    Roda ANTES de `gerar_manchetes` e antes de a pausa existir: os tempos saem
    do alinhamento do áudio já aparado, e é `silencio.inserir_pausas` que os
    consome. Depois da inserção o alinhamento muda, e `gerar_manchetes`
    recalcula tudo em cima do alinhamento novo — por isso as duas funções
    partem da mesma citação em vez de trocarem números entre si.
    """
    topicos = roteiro.get("topicos") or []
    if not topicos:
        return []
    return [
        instante
        for instante, _ in _marcos_dos_topicos(
            topicos, texto_video, alinhamento, dur_total
        )
    ]


def janelas(manchetes: list[dict]) -> list[tuple[float, float]]:
    """(início, fim) de cada manchete — o que as outras camadas devem evitar.

    A cartela toma o QUADRO INTEIRO no deslize: se ela entrar em
    cima de uma manchete, ela cobre exatamente o texto que divide a pauta. As
    manchetes vêm da estrutura do roteiro e por isso ganham a prioridade.
    """
    return [
        (float(m["inicio_s"]), float(m["inicio_s"]) + float(m["dur_s"]))
        for m in manchetes
    ]
