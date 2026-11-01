package com.tradutorrt.app.models

import com.tradutorrt.app.core.WhisperSize

/**
 * Um arquivo de modelo hospedado no Hugging Face. [revision] fixa o commit para que tamanho e hash
 * nao mudem embaixo do app; o SHA-256 e o "oid" LFS informado pela API do HF.
 */
data class ModelFile(
    val id: String,
    val title: String,
    val repo: String,
    val revision: String,
    val path: String,
    val size: Long,
    val sha256: String,
    val localName: String = path.substringAfterLast('/'),
) {
    val url: String get() = "https://huggingface.co/$repo/resolve/$revision/$path"
}

object ModelCatalog {
    /**
     * Silero VAD v6.2 — o MESMO arquivo do pacote oficial `silero-vad` 6.2.x (SHA-256 identico).
     * A copia antiga do onnx-community e uma versao anterior que diverge ate 0,8 por bloco do modelo atual.
     */
    val sileroVad = ModelFile(
        "vad", "Silero VAD v6.2 (ONNX)", "istupakov/silero-vad-onnx", "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6",
        "silero_vad.onnx", 2_327_524L, "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
        localName = "silero_vad_v6.2.onnx",
    )
    val smartTurn = ModelFile(
        "smartturn", "Smart Turn v3.2 (CPU, int8)", "pipecat-ai/smart-turn-v3", "f766f81d3cfdf7737ac64aad813d91bbfd56bf93",
        "smart-turn-v3.2-cpu.onnx", 8_679_182L, "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    )
    val whisperBase = ModelFile(
        "whisper-base", "Whisper base (q5_1)", "ggerganov/whisper.cpp", "5359861c739e955e79d9a303bcbc70fb988958b1",
        "ggml-base-q5_1.bin", 59_707_625L, "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
    )
    val whisperSmall = ModelFile(
        "whisper-small", "Whisper small (q5_1)", "ggerganov/whisper.cpp", "5359861c739e955e79d9a303bcbc70fb988958b1",
        "ggml-small-q5_1.bin", 190_085_487L, "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
    )

    /**
     * Hy-MT2-1.8B. O GGUF de 1.25 bit (tencent/Hy-MT2-1.8B-1.25Bit-GGUF) usa o tipo de tensor "STQ"
     * da PR #22836, que nao esta no llama.cpp upstream (o loader falha com "failed to read tensor data").
     * Por isso o app usa o Q4_K_M oficial.
     */
    val hyMt = ModelFile(
        "mt", "Hy-MT2-1.8B (GGUF Q4_K_M)", "tencent/Hy-MT2-1.8B-GGUF", "a0c709d9fac510f2c807aa3af52872340dc37a4a",
        "Hy-MT2-1.8B-Q4_K_M.gguf", 1_133_080_448L, "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699",
    )

    /** Soprano-1.1-80M em ONNX (mesma interface do tools/export_soprano_onnx.py deste repo). */
    private const val SOPRANO_REPO = "KevinAHM/soprano-1.1-onnx"
    private const val SOPRANO_REV = "ad2dfcc6948048555906085b7efd159c169dbded"
    val sopranoBackbone = ModelFile(
        "soprano-backbone", "Soprano-1.1-80M backbone (ONNX int8)", SOPRANO_REPO, SOPRANO_REV,
        "onnx/soprano_backbone_kv_int8.onnx", 80_938_986L,
        "a4b7b8406185396f14a0ee89e041e469edaeb7155efe7e5b6def57ff9acd15e4",
    )
    val sopranoDecoder = ModelFile(
        "soprano-decoder", "Soprano decoder Vocos (ONNX)", SOPRANO_REPO, SOPRANO_REV,
        "onnx/soprano_decoder_fp32.onnx", 262_812L,
        "1f6c3cd97c794d6c58c8edf4e3ce157c6465895098d062c5501d3170e837d947",
    )
    val sopranoDecoderData = ModelFile(
        "soprano-decoder-data", "Soprano decoder Vocos (pesos)", SOPRANO_REPO, SOPRANO_REV,
        "onnx/soprano_decoder_fp32.onnx.data", 121_503_744L,
        "02ba358c807c31966ec3f41ca1ceb9b5b82abf78786551b6067d7979e7dbf7fd",
    )

    val all: List<ModelFile> get() = listOf(sileroVad, smartTurn, whisperBase, whisperSmall, hyMt) + soprano

    fun whisper(size: WhisperSize) = if (size == WhisperSize.SMALL) whisperSmall else whisperBase

    val soprano = listOf(sopranoBackbone, sopranoDecoder, sopranoDecoderData)

    /** Arquivos necessarios para a configuracao atual. */
    fun required(whisperSize: WhisperSize, withSoprano: Boolean): List<ModelFile> =
        listOf(sileroVad, smartTurn, whisper(whisperSize), hyMt) + if (withSoprano) soprano else emptyList()
}
