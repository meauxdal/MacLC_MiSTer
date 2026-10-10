# Read-only post-fit gate for builds containing the 480i output stage.
# Run from the project root: quartus_sta -t scripts/check_tv525_timing.tcl
# Does not synthesize, fit, deploy, or change constraints. Reports go to a new
# scratch directory. Exit 2 means negative slack; missing evidence is an error.
# A pass covers the timed design and TV/CDC contracts, not every external board
# interface: review the unconstrained-path report separately.
package require ::quartus::project
package require ::quartus::sta

project_open MacLC
create_timing_netlist
read_sdc
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
required_registers {*crt_tv|pin_ready*}
required_registers {*crt_tv|pin_code_q[*]}
required_registers {*crt_tv|pin_tag_q[28]}
set tv_clock [get_clocks -nowarn {*tv525_pll|*|divclk}]
if {[get_collection_size $tv_clock] != 1} {error "Expected one TV clock"}
set ports [get_ports {VGA_R* VGA_G* VGA_B* VGA_HS VGA_VS SDIO_CLK SDIO_CMD SDIO_DAT* SD_SPI_CS}]
if {[get_collection_size $ports] != 27} {error "Expected all 27 TV output ports"}

foreach_in_collection op [get_available_operating_conditions] {
    set corner [get_operating_conditions_info -name $op]
    set_operating_conditions $op
    update_timing_netlist
    foreach check {setup hold recovery removal} {check_path $check -$check}
    check_path register_setup -setup -to [all_registers]
    set index 0
    foreach_in_collection port $ports {
        # A collection iterator returns a node ID, not a port collection.
        set endpoint [get_ports [get_node_info -name $port]]
        check_path output_[incr index] -setup -from_clock $tv_clock -to $endpoint
    }
    foreach name {gray_write gray_read config line reset pin_ready} pair {
        {{*crt_tv|*|capture_fifo|wr_gray[*]} {*crt_tv|*|capture_fifo|wr_gray_meta[*]}}
        {{*crt_tv|*|capture_fifo|rd_gray[*]} {*crt_tv|*|capture_fifo|rd_gray_meta[*]}}
        {{*crt_tv|*|config_payload*} {*crt_tv|*|tv_config*}}
        {{*crt_tv|*|line_payload[*]} {*crt_tv|*|store|address[*]}}
        {{*crt_tv|tv_reset_pipe[0]} {*crt_tv|tv_reset_pipe[1]}}
        {{*crt_tv|tv_reset_pipe[1]} {*crt_tv|pin_ready*}}
    } {
        check_path $name -setup -from [required_registers [lindex $pair 0]] -to [required_registers [lindex $pair 1]]
    }
    foreach dir {wr rd} {
        set meta [required_registers "*crt_tv|*|capture_fifo|${dir}_gray_meta\[*\]"]
        set sync [required_registers "*crt_tv|*|capture_fifo|${dir}_gray_sync\[*\]"]
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
report_ucp -file [file join $output unconstrained.rpt]
close $summary
delete_timing_netlist
project_close
puts "TIMING_GATE reports=$output failed_checks=$failures"
if {$failures != 0} {exit 2}
puts "TIMING_GATE PASS: no negative slack in the checked timing contracts at any available corner"
exit 0
