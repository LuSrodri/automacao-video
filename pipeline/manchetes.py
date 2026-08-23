"""Manchetes do formato longo: o texto que dá ritmo e divisão ao vídeo.

O problema (2026-08-23, diagnóstico do usuário): o vídeo longo é MONÓTONO. Ele
tem 135 segundos de narração corrida sobre clipes que trocam, sem nenhuma marca
de que a pauta mudou — o espectador não sabe onde está, não sabe o que ainda
vem, e não tem por que ficar.

Esta camada resolve isso com duas peças, ambas ancoradas em CITAÇÕES LITERAIS
da narração (o mesmo mecanismo das cartelas, das figuras e dos capítulos — o
único jeito de o texto na tela cair no segundo em que a narração diz aquilo):

1. AINDA NESTE EPISÓDIO — logo depois da pergunta de abertura, no canto
   inferior, por no MÁXIMO 10 segundos (ABERTURA_MAX_S): a lista do que o vídeo
   vai tratar, um tópico de cada vez. É a promessa que segura quem chegou pelo
   gancho e ainda não decidiu ficar.
2. UMA MANCHETE POR TÓPICO — quando a pauta vira, a manchete daquele tópico
   entra no mesmo canto. Junto com a VIRADA escrita no roteiro (ver
   escritor.py: cada tópico a partir do segundo abre com uma frase curta que
   fecha o anterior e nomeia o próximo), é o que transforma um bloco corrido
   em capítulos que o espectador percebe.

ESTILO — misto, definido em identidade.py: aranhaverso (desregistragem
ciano/magenta, retícula Ben-Day) sobre estrutura editorial minimalista
(retângulo preto, grotesca pesada em caixa alta, um fio, uma cor). O MOVIMENTO
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
    "brasil": "AINDA NESTE EPISÓDIO",
    "usa": "COMING UP",
}

# --- Tempo -------------------------------------------------------------------
ABERTURA_MAX_S = 10.0  # teto pedido para o bloco inteiro do índice
ABERTURA_ITEM_MIN_S = 1.7  # abaixo disso não dá tempo de ler o tópico
DUR_MANCHETE = 4.2  # tempo-alvo da manchete de um tópico na tela
DUR_MINIMA = 2.0
GAP = 0.7  # respiro entre uma peça e a seguinte
# O gancho fica limpo: nada de texto por cima da pergunta de abertura.
INICIO_MINIMO = 3.0
# Depois da pergunta, um respiro antes de o índice subir.
ATRASO_APOS_PERGUNTA = 0.35

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
FAIXA_FRAC = 0.0085  # largura da tarja de cor à esquerda
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
    faixa = max(4, round(altura_quadro * FAIXA_FRAC))
    tam_kicker = max(11, round(altura_quadro * KICKER_FRAC))
    f_kicker = ident.fonte(tam_kicker)
    # O tracking largo é o que faz uma linha pequena ler como RÓTULO. Num
    # kicker de duas letras ("02") ele só afasta os dois algarismos e o número
    # deixa de ser um número: aí o espaçamento sai.
    tracking = tam_kicker * TRACKING_FRAC if len(kicker) > 3 else 0.0

    util_max = largura_max - 2 * pad - faixa
    f_titulo, linhas = ident.caber(
        medidor, titulo.upper(), util_max, round(altura_quadro * TITULO_FRAC),
        minimo=max(16, round(altura_quadro * 0.028)), maximo_linhas=2,
    )

    larg_kicker = ident.largura_espacada(medidor, kicker, f_kicker, tracking)
    if contador:
        larg_kicker += pad + medidor.textlength(contador, font=f_kicker)
    larg_titulo = max(
        (medidor.textlength(linha, font=f_titulo) for linha in linhas), default=0
    )
    util = min(util_max, max(larg_kicker, larg_titulo))

    alt_linha = round(f_titulo.size * ENTRELINHA)
    # kicker + fio + linhas do título, tudo dentro do respiro do painel.
    alt_kicker = round(tam_kicker * 1.5)
    largura = round(faixa + 2 * pad + util)
    alt_conteudo = round(2 * pad + alt_kicker + alt_linha * len(linhas))
    altura = max(alt_conteudo, int(altura_minima))
    sobra = (altura - alt_conteudo) // 2

    tela = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr = ImageDraw.Draw(tela, "RGBA")
    dr.rectangle([0, 0, largura, altura], fill=(*ident.PRETO, FUNDO_ALFA))
    # Retícula bem fraca no corpo do painel: a textura de impressão que liga a
    # manchete à capa, sem virar ruído atrás do texto. Na tarja de cor ela não
    # cabe — com 16 px de largura a malha lê como tracejado, não como trama.
    ident.reticula(
        tela, (faixa, 0, largura, altura), cor=ident.BRANCO,
        passo=max(9, round(altura_quadro * 0.012)), raio=1, alfa=20,
    )
    # Tarja de cor à esquerda: o único bloco chapado da peça.
    dr.rectangle([0, 0, faixa, altura], fill=(*cor, 255))

    x = faixa + pad
    y = pad
    ident.escrever_espacado(dr, (x, y), kicker, f_kicker, (*cor, 255), tracking)
    if contador:
        dr.text(
            (largura - pad, y), contador, font=f_kicker,
            fill=(*ident.BRANCO, 150), anchor="ra",
        )
    # Fio fino sob o kicker: a marca editorial que separa rótulo de manchete.
    y_fio = y + round(tam_kicker * 1.15)
    dr.line(
        [(x, y_fio), (largura - pad, y_fio)], fill=(*ident.BRANCO, 55), width=1
    )

    y = pad + alt_kicker + sobra
    for linha in linhas:
        ident.escrever_cromatico(tela, (x, y), linha, f_titulo, ident.BRANCO)
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


def _inicio_do_indice(
    roteiro: dict, texto_video: str, alinhamento: dict, dur_total: float
) -> float:
    """Instante em que o índice sobe: logo depois da pergunta de abertura.

    A pergunta é a primeira frase do texto (regra do formato longo), e é ela
    que decide quem fica: nada entra por cima dela. Sem conseguir localizá-la,
    cai no piso fixo do gancho.
    """
    pergunta = " ".join((roteiro.get("pergunta") or "").split())
    if pergunta:
        pos = texto_video.lower().find(pergunta.lower())
        if pos >= 0:
            fim = min(pos + len(pergunta), len(texto_video) - 1)
            instante = _tempo_do_char(alinhamento, texto_video, fim, dur_total)
            return max(INICIO_MINIMO, instante + ATRASO_APOS_PERGUNTA)
    return INICIO_MINIMO


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

        # --- 1. AINDA NESTE EPISÓDIO ---------------------------------------
        inicio_indice = _inicio_do_indice(
            roteiro, texto_video, alinhamento, dur_total
        )
        # O índice tem que ACABAR antes de a primeira pauta entrar: ele promete
        # o que vem, e prometer por cima do primeiro tópico já entregue é ruído.
        limite = marcos[0][0] - GAP if marcos else dur_total * 0.45
        disponivel = min(ABERTURA_MAX_S, limite - inicio_indice)
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

        # --- 2. Uma manchete por tópico -------------------------------------
        for k, (inicio, titulo) in enumerate(marcos, 1):
            proximo = marcos[k][0] if k < len(marcos) else dur_total
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


def janelas(manchetes: list[dict]) -> list[tuple[float, float]]:
    """(início, fim) de cada manchete — o que as outras camadas devem evitar.

    Cartela e figura tomam o QUADRO INTEIRO no deslize: se uma delas entrar em
    cima de uma manchete, ela cobre exatamente o texto que divide a pauta. As
    manchetes vêm da estrutura do roteiro e por isso ganham a prioridade.
    """
    return [
        (float(m["inicio_s"]), float(m["inicio_s"]) + float(m["dur_s"]))
        for m in manchetes
    ]
