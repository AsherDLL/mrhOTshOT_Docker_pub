# CMakeLists.txt for PIPEDREAM C++ Components
# Builds Dusttunnel and Lazycargo for Windows
#
# Usage:
#   mkdir build && cd build
#   cmake .. -G "Visual Studio 16 2019" -A x64
#   cmake --build . --config Release

cmake_minimum_required(VERSION 3.10)

project(PIPEDREAM_CPP_Components VERSION 1.0 LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Windows-only components
if(WIN32)
    # Dusttunnel - Windows Persistence Module
    add_executable(dusttunnel
        dusttunnel/dusttunnel.cpp
    )

    target_link_libraries(dusttunnel
        wininet
        advapi32
    )

    # Lazycargo - ASRock Driver Exploit Module
    add_executable(lazycargo
        lazycargo/lazycargo.cpp
    )

    target_link_libraries(lazycargo
        advapi32
    )

    # Set output directories
    set_target_properties(dusttunnel lazycargo
        PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    )

    message(STATUS "Building PIPEDREAM C++ components for Windows")
    message(STATUS "  - Dusttunnel: Windows Persistence Module")
    message(STATUS "  - Lazycargo: ASRock Driver Exploit Module")
else()
    message(WARNING "PIPEDREAM C++ components are Windows-only")
endif()

# Installation
install(TARGETS dusttunnel lazycargo
    RUNTIME DESTINATION bin
)
