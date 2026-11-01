// Teste de ponta a ponta no host (Linux x86-64), fora do APK.
// Compila os MESMOS arquivos-fonte do app que nao dependem do Android e roda o pipeline sobre um WAV,
// usando os JNI de whisper/llama compilados para o host (ver tools/build_host_jni.sh).
plugins {
    id("org.jetbrains.kotlin.jvm")
    application
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

sourceSets {
    main {
        kotlin {
            srcDir("../app/src/main/java")
            srcDir("../whisper-jni/src/main/java")
            srcDir("../llama-jni/src/main/java")
            include(
                "HostE2E.kt",
                "com/tradutorrt/app/audio/WhisperFeatures.kt",
                "com/tradutorrt/app/audio/SileroVad.kt",
                "com/tradutorrt/app/audio/SmartTurn.kt",
                "com/tradutorrt/app/audio/TurnDetector.kt",
                "com/tradutorrt/app/core/Languages.kt",
                "com/tradutorrt/app/pipeline/TranslationPrompt.kt",
                "com/tradutorrt/app/tts/SopranoText.kt",
                "com/tradutorrt/app/tts/SopranoTts.kt",
                "com/tradutorrt/whisper/**",
                "com/tradutorrt/llama/**",
            )
        }
    }
}

dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime:1.23.2")
}

application {
    mainClass.set("HostE2EKt")
}

tasks.named<JavaExec>("run") {
    workingDir = rootProject.projectDir
    jvmArgs("-Dstdout.encoding=UTF-8", "-Dfile.encoding=UTF-8", "-Djava.library.path=" + (System.getenv("HOST_JNI_DIR") ?: "build/hostjni"), "-Xmx4g")
}
