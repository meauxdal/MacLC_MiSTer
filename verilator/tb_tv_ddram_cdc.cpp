#include "Vtv_ddram_cdc.h"
#include "verilated.h"
#include <iostream>
#include <stdexcept>

struct Sim {
    Vtv_ddram_cdc t;
    unsigned time=0, delay=0, issued=0, read_address=0;
    static uint64_t value(unsigned address) {return 0x123456789abcdef0ull^(uint64_t(address)*99991);}
    struct Sample {bool source_edge, accepted, valid;uint64_t data;};
    Sample step() {
        t.clk_mem=time%2; t.clk_source=(time/2)%2;
        bool memory_edge=time%2==1,source_edge=time%4==2;
        if(memory_edge) {
            t.waitrequest=time%11<3;
            t.readdatavalid=delay==1;
            t.readdata=value(read_address);
        }
        // Evaluate low clocks before sampling the source handshake.
        auto mem=t.clk_mem,src=t.clk_source;
        if(memory_edge)t.clk_mem=0;
        if(source_edge)t.clk_source=0;
        t.eval();
        Sample result{source_edge,source_edge&&(t.source_read||t.source_write)&&!t.source_waitrequest,
                      source_edge&&bool(t.source_readdatavalid),t.source_readdata};
        if(memory_edge) {
            if(delay)--delay;
            if((t.read||t.write)&&!t.waitrequest) {
                ++issued;
                if(t.write && (t.writedata!=value(t.address)||t.byteenable!=0xa5))throw std::runtime_error("Command payload changed");
                if(t.read) {read_address=t.address;delay=9+time%23;}
            }
        }
        t.clk_mem=mem;t.clk_source=src;t.eval();++time;
        if(time>200000)throw std::runtime_error("Timeout");
        return result;
    }
    void transfer(unsigned address,bool read,bool abort=false) {
        t.source_address=address;t.source_writedata=value(address);t.source_byteenable=0xa5;
        t.source_read=read;t.source_write=!read;
        bool accepted=false,done=false;unsigned begin=time,issued_before=issued;
        while(!done) {
            if(abort && time-begin==16) {t.reset_source=1;t.source_read=0;t.source_write=0;}
            if(abort && time-begin==40)t.reset_source=0;
            auto s=step();
            if(s.accepted) {if(accepted)throw std::runtime_error("Duplicate acceptance");accepted=true;t.source_read=0;t.source_write=0;}
            if(s.valid) {
                if(abort||!accepted||s.data!=value(address))throw std::runtime_error("Stale or premature response");
                done=true;
            }
            if(!read && accepted)done=true;
            if(abort && time-begin>160)done=true;
        }
        for(unsigned i=0;i<8;++i)step();
        if(issued-issued_before!=1)throw std::runtime_error("Command did not drain once");
    }
};
int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Sim s;s.t.reset_source=0;s.t.source_read=0;s.t.source_write=0;s.t.waitrequest=1;s.t.readdatavalid=0;
        for(unsigned i=1;i<=200;++i) {
            s.transfer(i,true);s.transfer(i,false);
            if(i%4==0) {s.transfer(i+1000,true,true);s.transfer(i+2000,false,true);}
        }
        std::cout<<"PASS Ethernet CDC: 400 normal commands, 100 reset-abandoned commands, stalls and delayed responses\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
