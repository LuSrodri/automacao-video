cmake_minimum_required(VERSION 3.22)
# O AGP passa CMAKE_BUILD_TYPE=Debug no assembleDebug; com -O0 o ggml fica 10-50x mais lento.
set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
project(whisper_jni C CXX)

set(CMAKE_CXX_STANDARD 17)
set(WHISPER_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/whisper.cpp)

set(BUILD_SHARED_LIBS        OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE              OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP              OFF CACHE BOOL "" FORCE)
set(GGML_CPU_ARM_ARCH        "armv8.2-a+dotprod+fp16" CACHE STRING "" FORCE)
set(WHISPER_BUILD_TESTS      OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES   OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER     OFF CACHE BOOL "" FORCE)
set(WHISPER_SDL2             OFF CACHE BOOL "" FORCE)
set(WHISPER_CURL             OFF CACHE BOOL "" FORCE)

add_subdirectory(${WHISPER_DIR} whisper-build)

add_library(whisper_jni SHARED whisper_jni.cpp)
target_link_libraries(whisper_jni PRIVATE whisper log)
# ggml estatico e escondido: nao colide com o ggml do llama_jni carregado no mesmo processo
target_link_options(whisper_jni PRIVATE -Wl,--exclude-libs,ALL -Wl,--gc-sections -Wl,-z,max-page-size=16384)
