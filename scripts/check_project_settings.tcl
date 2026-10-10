# User-run settings preflight; no synthesis, fit, STA, or assignment export.
# PowerShell: quartus_sh -t scripts/check_project_settings.tcl
package require ::quartus::project

proc read_qsf_bytes {} {
    set handle [open MacLC.qsf rb]
    set bytes [read $handle]
    close $handle
    return $bytes
}

set original_qsf [read_qsf_bytes]
if {[catch {
    if {[regexp -- {-to\s+\{} $original_qsf]} {
        error "QSF node targets cannot use Tcl braces; Quartus treats them literally"
    }
    project_open -revision MacLC MacLC
    foreach {name expected} {
        TOP_LEVEL_ENTITY sys_top
        DEVICE 5CSEBA6U23I7
        TIMEQUEST_MULTICORNER_ANALYSIS ON
    } {
        set actual [get_global_assignment -name $name]
        puts "SETTINGS $name=$actual"
        if {![string equal -nocase $actual $expected]} {
            error "Expected $name=$expected; got $actual"
        }
    }
    set tv_enabled 0
    foreach_in_collection assignment [get_all_global_assignments -name VERILOG_MACRO] {
        set value [lindex $assignment 2]
        if {$value eq "MAC_TV525_DIAG=1"} {set tv_enabled 1}
        if {[string match "MAC_TV525_DIAG=*" $value] && $value ne "MAC_TV525_DIAG=1"} {
            error "Conflicting TV diagnostic macro: $value"
        }
    }
    if {!$tv_enabled} {error "MAC_TV525_DIAG=1 is required for this timing review"}
    set project_sdc 0
    foreach_in_collection assignment [get_all_global_assignments -name SDC_FILE] {
        set value [lindex $assignment 2]
        puts "SETTINGS SDC_FILE=$value"
        if {$value eq "MacLC.sdc"} {set project_sdc 1}
    }
    if {!$project_sdc} {error "Project timing constraints MacLC.sdc are missing"}
    project_close -dont_export_assignments
    if {[read_qsf_bytes] ne $original_qsf} {
        error "MacLC.qsf changed during settings preflight; inspect the saved before/after files"
    }
} failure]} {
    puts stderr "SETTINGS_PREFLIGHT FAILED: $failure"
    puts stderr $::errorInfo
    if {[is_project_open]} {catch {project_close -dont_export_assignments}}
    exit 1
}
puts "SETTINGS_PREFLIGHT PASS: settings opened without exporting assignments"
puts "This checks current project settings only; synthesis-time and SDC diagnostics still require the compile log."
exit 0
