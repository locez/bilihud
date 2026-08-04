cmake_minimum_required(VERSION 3.16)

project(bilihud LANGUAGES NONE)

set(BILIHUD_LAYER_SHELL "AUTO" CACHE STRING
    "Build the Linux Layer Shell bridge: AUTO, ON, or OFF")
set_property(CACHE BILIHUD_LAYER_SHELL PROPERTY STRINGS AUTO ON OFF)
string(TOUPPER "${BILIHUD_LAYER_SHELL}" BILIHUD_LAYER_SHELL_MODE)

set(BILIHUD_LAYER_SHELL_INPLACE_OUTPUT "")
if(CMAKE_BINARY_DIR STREQUAL CMAKE_SOURCE_DIR)
    set(
        BILIHUD_LAYER_SHELL_INPLACE_OUTPUT
        "${CMAKE_SOURCE_DIR}/src/bilihud/libbili-layer.so"
    )
endif()

function(remove_inplace_layer_shell_bridge)
    if(BILIHUD_LAYER_SHELL_INPLACE_OUTPUT)
        file(REMOVE "${BILIHUD_LAYER_SHELL_INPLACE_OUTPUT}")
    endif()
endfunction()

if(NOT BILIHUD_LAYER_SHELL_MODE MATCHES "^(AUTO|ON|OFF)$")
    message(FATAL_ERROR
        "BILIHUD_LAYER_SHELL must be AUTO, ON, or OFF, got: ${BILIHUD_LAYER_SHELL}")
endif()

if(BILIHUD_LAYER_SHELL_MODE STREQUAL "OFF")
    remove_inplace_layer_shell_bridge()
    message(STATUS "Layer Shell bridge disabled by BILIHUD_LAYER_SHELL=OFF")
    return()
endif()

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    remove_inplace_layer_shell_bridge()
    if(BILIHUD_LAYER_SHELL_MODE STREQUAL "ON")
        message(FATAL_ERROR "The Layer Shell bridge is only supported on Linux")
    endif()
    message(STATUS "Layer Shell bridge skipped on ${CMAKE_SYSTEM_NAME}")
    return()
endif()

include(CheckLanguage)
check_language(CXX)
set(BILIHUD_LAYER_SHELL_MISSING "")

if(NOT CMAKE_CXX_COMPILER)
    list(APPEND BILIHUD_LAYER_SHELL_MISSING "C++ compiler")
else()
    enable_language(CXX)

    find_package(Qt6 QUIET COMPONENTS Core Gui GuiPrivate)
    if(NOT TARGET Qt6::Core OR NOT TARGET Qt6::Gui OR NOT TARGET Qt6::GuiPrivate)
        list(APPEND BILIHUD_LAYER_SHELL_MISSING "Qt6 Core/Gui private development files")
    endif()

    find_package(LayerShellQt QUIET CONFIG)
    if(NOT TARGET LayerShellQt::Interface)
        list(APPEND BILIHUD_LAYER_SHELL_MISSING "LayerShellQt development files")
    endif()

    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(WAYLAND_CLIENT QUIET IMPORTED_TARGET wayland-client)
    endif()
    if(NOT TARGET PkgConfig::WAYLAND_CLIENT)
        list(APPEND BILIHUD_LAYER_SHELL_MISSING "wayland-client development files")
    endif()
endif()

if(BILIHUD_LAYER_SHELL_MISSING)
    remove_inplace_layer_shell_bridge()
    list(JOIN BILIHUD_LAYER_SHELL_MISSING ", " BILIHUD_LAYER_SHELL_MISSING_TEXT)
    if(BILIHUD_LAYER_SHELL_MODE STREQUAL "ON")
        message(FATAL_ERROR
            "Layer Shell bridge requested but dependencies are missing: "
            "${BILIHUD_LAYER_SHELL_MISSING_TEXT}")
    endif()
    message(STATUS
        "Layer Shell bridge skipped; missing: ${BILIHUD_LAYER_SHELL_MISSING_TEXT}")
    return()
endif()

add_library(bilihud_layer_shell SHARED src/bilihud/layer_shell_bridge.cpp)
target_compile_features(bilihud_layer_shell PRIVATE cxx_std_17)
target_link_libraries(
    bilihud_layer_shell
    PRIVATE
        Qt6::Core
        Qt6::Gui
        Qt6::GuiPrivate
        LayerShellQt::Interface
        PkgConfig::WAYLAND_CLIENT
)
set_target_properties(
    bilihud_layer_shell
    PROPERTIES
        OUTPUT_NAME "bili-layer"
        PREFIX "lib"
)

# In-place editable builds use the source directory as their CMake build tree.
# Keep the bridge beside the Python package so imports can load it directly.
if(BILIHUD_LAYER_SHELL_INPLACE_OUTPUT)
    set_target_properties(
        bilihud_layer_shell
        PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/src/bilihud/$<0:>"
    )
endif()

install(
    TARGETS bilihud_layer_shell
    LIBRARY DESTINATION bilihud
    RUNTIME DESTINATION bilihud
    ARCHIVE DESTINATION bilihud
)
