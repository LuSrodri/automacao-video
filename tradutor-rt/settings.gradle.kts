pluginManagement {
    repositories {
        google()
        // espelho oficial do Maven Central no Google Cloud (evita HTTP 429 do repo1 em builds paralelos)
        maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        // espelho oficial do Maven Central no Google Cloud (evita HTTP 429 do repo1 em builds paralelos)
        maven("https://maven-central.storage-download.googleapis.com/maven2/")
        mavenCentral()
    }
}
rootProject.name = "TradutorRT"
include(":app", ":whisper-jni", ":llama-jni")
// teste de ponta a ponta no host (opcional, nao entra no APK)
if (file("hosttest").exists()) include(":hosttest")
