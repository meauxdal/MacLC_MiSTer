# From the repository root: make -f tests/iie/tv525.mk check
V ?= verilator
TV_FILTER_ENABLE ?= 0
TV_BASE_HEX ?= 2180000
TV_SOURCE_WIDTH ?= 0
TV_SOURCE_HEIGHT ?= 0
TV_OBJ = tests/iie/obj_tv525_pipeline_$(TV_FILTER_ENABLE)_$(TV_BASE_HEX)_$(TV_SOURCE_WIDTH)_$(TV_SOURCE_HEIGHT)
TV_RTL = rtl/tv525_pipeline.sv rtl/tv525_video.sv rtl/tv525_timing.sv \
         rtl/tv_buffered_canvas.sv rtl/tv_video_capture.sv rtl/tv_capture_fifo.sv \
         rtl/tv_frame_store.sv rtl/tv_deflicker.sv rtl/tv_ddram_bridge.sv
TV_FLAGS = --Wall -Wno-PINCONNECTEMPTY --top-module tv525_pipeline \
           -GFILTER_ENABLE=$(TV_FILTER_ENABLE) "-GBASE_WORD=28'h$(TV_BASE_HEX)" \
           -GSOURCE_WIDTH=$(TV_SOURCE_WIDTH) -GSOURCE_HEIGHT=$(TV_SOURCE_HEIGHT)

.PHONY: check lint
lint:
	$(V) --lint-only $(TV_FLAGS) $(TV_RTL)
check: lint
	$(V) --cc --exe --build -j 4 $(TV_FLAGS) --Mdir $(TV_OBJ) \
	    -o tb_tv525_pipeline -CFLAGS "-std=c++17 -O2 -DTV_FILTER_ENABLE=$(TV_FILTER_ENABLE) -DTV_BASE_WORD=0x$(TV_BASE_HEX) -DTV_SOURCE_WIDTH=$(TV_SOURCE_WIDTH) -DTV_SOURCE_HEIGHT=$(TV_SOURCE_HEIGHT)" \
	    $(TV_RTL) tests/iie/tb_tv525_pipeline.cpp
	./$(TV_OBJ)/tb_tv525_pipeline
