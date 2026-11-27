cmake_minimum_required(VERSION 3.20)
project(fedora_dpf_probe LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Concurrent)
find_path(DFM_FRAMEWORK_INCLUDE_DIR NAMES dfm-framework/event/event.h
          PATH_SUFFIXES dfm6-framework REQUIRED)
find_library(DFM_FRAMEWORK_LIBRARY NAMES dfm6-framework REQUIRED)

add_executable(dpf-probe-host host.cpp)
target_link_libraries(dpf-probe-host PRIVATE Qt6::Core)
foreach(plugin IN ITEMS outer inner)
    add_library(dpf-probe-${plugin} MODULE ${plugin}.cpp)
    set_target_properties(dpf-probe-${plugin} PROPERTIES PREFIX "")
    target_include_directories(dpf-probe-${plugin} PRIVATE ${DFM_FRAMEWORK_INCLUDE_DIR})
    target_link_libraries(dpf-probe-${plugin} PRIVATE Qt6::Core Qt6::Concurrent ${DFM_FRAMEWORK_LIBRARY})
endforeach()

enable_testing()
add_test(NAME packaged_dpf_nested_plugins COMMAND dpf-probe-host
         $<TARGET_FILE:dpf-probe-outer> $<TARGET_FILE:dpf-probe-inner>)
