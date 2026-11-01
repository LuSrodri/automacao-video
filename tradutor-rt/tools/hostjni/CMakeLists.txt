# Build dos MESMOS JNI do app para Linux x86-64 (teste de ponta a ponta no host, modulo :hosttest).
cmake_minimum_required(VERSION 3.22)
project(hostjni C CXX)
set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
find_package(JNI REQUIRED)
set(ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../..)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE ON CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
foreach(o LLAMA_BUILD_TESTS LLAMA_BUILD_EXAMPLES LLAMA_BUILD_TOOLS LLAMA_BUILD_SERVER LLAMA_BUILD_COMMON LLAMA_CURL
          LLAMA_OPENSSL LLAMA_BUILD_APP LLAMA_BUILD_HTML WHISPER_BUILD_TESTS WHISPER_BUILD_EXAMPLES WHISPER_BUILD_SERVER
          WHISPER_SDL2 WHISPER_CURL)
  set(${o} OFF CACHE BOOL "" FORCE)
endforeach()

# llama.cpp e whisper.cpp trazem cada um o seu ggml: usa o do llama.cpp como alvo "ggml" e compila
# o whisper.cpp num subprojeto externo para nao colidir nomes de alvos.
add_subdirectory(${ROOT}/third_party/llama.cpp llama-build)
add_library(llama_jni SHARED ${ROOT}/llama-jni/src/main/cpp/llama_jni.cpp)
target_include_directories(llama_jni PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${JNI_INCLUDE_DIRS})
target_link_libraries(llama_jni PRIVATE llama)
target_link_options(llama_jni PRIVATE -Wl,--exclude-libs,ALL)

include(ExternalProject)
ExternalProject_Add(whisper_host
  SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/whisper
  BINARY_DIR ${CMAKE_BINARY_DIR}/whisper-host
  CMAKE_ARGS -DROOT=${ROOT} -DCMAKE_BUILD_TYPE=Release -DOUT_DIR=${CMAKE_BINARY_DIR}
  INSTALL_COMMAND "")
