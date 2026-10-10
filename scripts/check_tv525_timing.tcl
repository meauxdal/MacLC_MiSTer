# Read-only post-fit gate for builds containing the 480i output stage.
# Run from the project root: quartus_sta -t scripts/check_tv525_timing.tcl
# Run that command in an OS terminal, not the main Quartus Prime Tcl Console.
# Does not synthesize, fit, deploy, or change constraints. Reports go to a new
# scratch directory. Exit 2 means negative slack; missing evidence is an error.
# A pass covers the timed design and TV/CDC contracts, not every external board
# interface: review the unconstrained-path report separately.
package require ::quartus::project
if {[catch {package require ::quartus::sta} sta_package_error]} {
    error "This script requires quartus_sta. Run in PowerShell from C:/Workspace/Git/MacLC_MiSTer: quartus_sta -t scripts/check_tv525_timing.tcl\n$sta_package_error"
}

project_open MacLC
create_timing_netlist
set maclc_sdc_loaded 0
read_sdc
if {!$maclc_sdc_loaded} {error "MacLC.sdc did not finish loading; timing results are incomplete"}
update_timing_netlist

set output [file join scratch timing_gate [clock format [clock seconds] -format %Y%m%d_%H%M%S]]
file mkdir $output
set summary [open [file join $output summary.tsv] w]
puts $summary "corner\tcheck\tslack_ns\tfrom\tto"
set failures 0

proc required_registers {pattern} {
    set result [get_registers -nowarn $pattern]
    if {[get_collection_size $result] == 0} {
        error "Required fitted registers missing: $pattern"
    }
    return $result
}

proc check_path {label args} {
    global corner output summary failures
    set command [linsert $args 0 get_timing_paths]
    lappend command -npaths 1
    set paths [eval $command]
    if {[get_collection_size $paths] == 0} {
        error "Required timed path missing: $label ($corner)"
    }
    foreach_in_collection path $paths {
        set slack [get_path_info -slack $path]
        set from [get_node_info -name [get_path_info -from $path]]
        set to [get_node_info -name [get_path_info -to $path]]
        puts $summary "$corner\t$label\t$slack\t$from\t$to"
        puts "CHECK $corner $label slack=$slack"
        if {$slack < 0.0} {incr failures}
    }
    set command [linsert $args 0 report_timing]
    lappend command -npaths 1 -detail full_path -file [file join $output ${corner}_${label}.rpt]
    eval $command
}

# Reject pre-optimization databases instead of attributing them to current RTL.
required_registers {*crt_tv|pin_tag_q[28]}
set tv_clock [get_clocks -nowarn {*tv525_pll|*|divclk}]
if {[get_collection_size $tv_clock] != 1} {error "Expected one TV clock"}
set ports [get_ports {VGA_R* VGA_G* VGA_B* VGA_HS VGA_VS SDIO_CLK SDIO_CMD SDIO_DAT* SD_SPI_CS}]
if {[get_collection_size $ports] != 27} {error "Expected all 27 TV output ports"}
set native_clock [get_clocks {emu|pllv|*|divclk}]
set main_clocks [get_clocks {*emu|pll|pll_inst|*|divclk}]
set memory_clock [remove_from_collection $main_clocks $main_clocks]
foreach_in_collection clock $main_clocks {
    if {abs([get_clock_info -period $clock] - 1000.0/65) < 0.01} {
        set memory_clock [add_to_collection $memory_clock \
            [get_clocks [get_clock_info -name $clock]]]
    }
}
if {[get_collection_size $native_clock] != 1 || [get_collection_size $memory_clock] != 1} {
    error "Expected native video and FIFO memory clocks"
}
set hdmi_clock [get_clocks -nowarn {pll_hdmi|pll_hdmi_inst|*|divclk}]
if {[get_collection_size $hdmi_clock] != 1} {error "Expected one HDMI output PLL clock"}
set hdmi_output_registers [required_registers {*hdmi_out_d[*]*}]
set checked_corners {}

foreach_in_collection op [get_available_operating_conditions] {
    set corner [get_operating_conditions_info -name $op]
    lappend checked_corners $corner
    set_operating_conditions $op
    update_timing_netlist
    # Both clocks reach this bank through hdmi_clk_sw. Require surviving
    # same-clock paths in each selectable mode; global slack alone cannot
    # detect clock exceptions that inadvertently remove one of these paths.
    foreach check {setup hold} {
        check_path hdmi_output_${check} -$check \
            -from_clock $hdmi_clock -to_clock $hdmi_clock -to $hdmi_output_registers
        check_path direct_video_output_${check} -$check \
            -from_clock $tv_clock -to_clock $tv_clock -to $hdmi_output_registers
    }
    foreach check {setup hold recovery removal} {check_path $check -$check}
    check_path register_setup -setup -to [all_registers]
    # Check the RTL's explicit clock ownership as well as the physical budget.
    # These patterns include fitted router copies, just like MacLC.sdc.
    check_path gray_write -setup -from_clock $native_clock -to_clock $memory_clock \
        -from [required_registers {*crt_tv|*|capture_fifo|wr_gray[*]*}] \
        -to [required_registers {*crt_tv|*|capture_fifo|wr_gray_meta[*]*}]
    check_path gray_read -setup -from_clock $memory_clock -to_clock $native_clock \
        -from [required_registers {*crt_tv|*|capture_fifo|rd_gray[*]*}] \
        -to [required_registers {*crt_tv|*|capture_fifo|rd_gray_meta[*]*}]
    foreach name {line reset} pair {
        {{*crt_tv|*|line_payload[*]} {*crt_tv|*|store|address[*]}}
        {{*emu|tv_reset_pipe[0]} {*emu|tv_reset_pipe[1]}}
    } {
        check_path $name -setup -from [required_registers [lindex $pair 0]] -to [required_registers [lindex $pair 1]]
    }
    foreach dir {wr rd} {
        set meta [required_registers "*crt_tv|*|capture_fifo|${dir}_gray_meta\[*\]*"]
        set sync [required_registers "*crt_tv|*|capture_fifo|${dir}_gray_sync\[*\]*"]
        foreach check {setup hold} {check_path ${dir}_synchronizer_${check} -$check -from $meta -to $sync}
    }
    set skew_file [file join $output ${corner}_skew.rpt]
    report_max_skew -detail full_path -file $skew_file
    set handle [open $skew_file r]
    set skew_text [read $handle]
    close $handle
    if {![regexp {Report Max Skew: Found ([0-9]+) paths \(([0-9]+) violated\)} $skew_text -> count violations] || $count < 4} {
        error "Missing FIFO skew evidence at $corner (see $skew_file)"
    }
    incr failures $violations
}
foreach required_corner {7_slow_1100mv_100c 7_slow_1100mv_-40c MIN_fast_1100mv_100c MIN_fast_1100mv_-40c} {
    if {[lsearch -exact $checked_corners $required_corner] < 0} {
        error "Required operating corner missing: $required_corner (checked $checked_corners)"
    }
}
report_ucp -file [file join $output unconstrained.rpt]
close $summary
delete_timing_netlist
project_close -dont_export_assignments
puts "TIMING_GATE reports=$output failed_checks=$failures"
if {$failures != 0} {exit 2}
puts "TIMING_GATE PASS: no negative slack in the checked timing contracts at any available corner"
exit 0
