# Read-only post-fit gate for the Apple IIe card measurement branch.
# Run from the project root: quartus_sta -t scripts/check_native_timing.tcl
package require ::quartus::project
package require ::quartus::sta

project_open MacLC
create_timing_netlist
set maclc_sdc_loaded 0
read_sdc
if {!$maclc_sdc_loaded} {error "MacLC.sdc did not finish loading"}
update_timing_netlist

set native_clock [get_clocks {emu|pllv|*|divclk}]
if {[get_collection_size $native_clock] != 1} {error "Expected one native video clock"}
foreach pattern {*crt_tv|* *pds_enet|* *cdrom_target|* *floppyExt|*} {
    if {[get_collection_size [get_registers -nowarn $pattern]] != 0} {
        error "Removed hardware remains in the fitted database: $pattern"
    }
}

set output [file join scratch timing_gate [clock format [clock seconds] -format %Y%m%d_%H%M%S]]
file mkdir $output
set summary [open [file join $output summary.tsv] w]
puts $summary "corner\tcheck\tslack_ns\tfrom\tto"
set failures 0
set checked_corners {}

foreach_in_collection op [get_available_operating_conditions] {
    set corner [get_operating_conditions_info -name $op]
    lappend checked_corners $corner
    set_operating_conditions $op
    update_timing_netlist
    foreach check {setup hold recovery removal} {
        set paths [get_timing_paths -$check -npaths 1]
        if {[get_collection_size $paths] == 0} {
            error "Required timed path missing: $check ($corner)"
        }
        foreach_in_collection path $paths {
            set slack [get_path_info -slack $path]
            set from [get_node_info -name [get_path_info -from $path]]
            set to [get_node_info -name [get_path_info -to $path]]
            puts $summary "$corner\t$check\t$slack\t$from\t$to"
            puts "CHECK $corner $check slack=$slack"
            if {$slack < 0.0} {incr failures}
        }
        report_timing -$check -npaths 1 -detail full_path \
            -file [file join $output ${corner}_${check}.rpt]
    }
}
foreach required_corner {7_slow_1100mv_100c 7_slow_1100mv_-40c MIN_fast_1100mv_100c MIN_fast_1100mv_-40c} {
    if {[lsearch -exact $checked_corners $required_corner] < 0} {
        error "Required operating corner missing: $required_corner"
    }
}
report_ucp -file [file join $output unconstrained.rpt]
close $summary
delete_timing_netlist
project_close -dont_export_assignments
puts "TIMING_GATE reports=$output failed_checks=$failures"
if {$failures != 0} {exit 2}
puts "TIMING_GATE PASS: review unconstrained paths separately"
exit 0
