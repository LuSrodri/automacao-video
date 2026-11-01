cmake_minimum_required(VERSION 3.22)
# O AGP passa CMAKE_BUILD_TYPE=Debug no assembleDebug; com -O0 o ggml fica 10-50x mais lento.
set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
project(llama_jni C CXX)

set(CMAKE_CXX_STANDARD 17)
set(LLAMA_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/llama.cpp)

set(BUILD_SHARED_LIBS        OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE              OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP              OFF CACHE BOOL "" FORCE)
set(GGML_CPU_ARM_ARCH        "armv8.2-a+dotprod+fp16" CACHE STRING "" FORCE)

set(LLAMA_BUILD_TESTS        OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS        OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER       OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON       OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL               OFF CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL            OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP          OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_HTML         OFF CACHE BOOL "" FORCE)

add_subdirectory(${LLAMA_DIR} llama-build)

add_library(llama_jni SHARED llama_jni.cpp)
target_link_libraries(llama_jni PRIVATE llama log)
# ggml estatico e escondido: nao colide com o ggml do whisper_jni carregado no mesmo processo
target_link_options(llama_jni PRIVATE -Wl,--exclude-libs,ALL -Wl,--gc-sections -Wl,-z,max-page-size=16384)
