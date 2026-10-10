#include "Vtv_ddram_pipeline.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <stdexcept>

using Word=std::array<uint32_t,4>;
static Word pattern(unsigned n,unsigned i) {
    return {0x11223344u^(n*19+i),0xdeadbeefu^(i*997),0xabcdef01u^(i*23),0x87654321u^(n+i*31)};
}
struct Sim {
    Vtv_ddram_pipeline t;
    std::map<uint32_t,uint64_t> memory, expected;
    std::deque<uint64_t> responses;
    unsigned cycles=0, write_left=0, write_index=0, write_base=0, read_base=0, commands=0, ether=0, resets=0;
    unsigned inhibit_left=0;
    bool ether_wait=false;
    struct Sample { bool source_accept, valid; Word data; };
    Sample step() {
        t.clk=0;
        if (!inhibit_left && cycles%31==0 &&
            ((write_left>2 && write_base>=0x4300000) || (responses.size()>2 && read_base>=0x4300000))) {
            inhibit_left=5; ++resets;
        }
        t.inhibit=inhibit_left!=0;
        t.waitrequest=cycles%7==0 || cycles%11==3;
        t.readdatavalid=!responses.empty() && cycles%5!=0;
        t.readdata=responses.empty()?0:responses.front();
        t.a_address=0x10000+(ether%64);
        t.a_writedata=0xcafe000000000000ull+ether;
        t.a_read=!ether_wait && ether%2==0;
        t.a_write=!ether_wait && ether%2==1;
        t.eval();
        Sample s{(t.source_read || t.source_write) && !t.source_waitrequest,
                 bool(t.source_readdatavalid), {t.source_readdata[0],t.source_readdata[1],t.source_readdata[2],t.source_readdata[3]}};
        bool a_accept=(t.a_read||t.a_write)&&!t.a_waitrequest;
        bool a_valid=t.a_readdatavalid;
        if (a_valid && t.a_readdata!=memory[t.a_address]) throw std::runtime_error("Ethernet response routing");
        if (t.readdatavalid) responses.pop_front();
        if ((t.read || t.write) && !t.waitrequest) {
            if (t.read) {
                if (write_left || !responses.empty()) throw std::runtime_error("Overlapping commands");
                if (!t.burstcount) throw std::runtime_error("Zero read burst");
                read_base=t.address;
                for (unsigned i=0;i<t.burstcount;++i) responses.push_back(memory[t.address+i]);
                ++commands;
            } else {
                if (!write_left) {
                    if (!t.burstcount) throw std::runtime_error("Zero write burst");
                    write_base=t.address; write_index=0; write_left=t.burstcount; ++commands;
                }
                if (t.address!=write_base) throw std::runtime_error("Address changed within burst");
                uint64_t mask=0;
                for (unsigned b=0;b<8;++b) if ((t.byteenable>>b)&1) mask|=0xffull<<(b*8);
                auto &word=memory[write_base+write_index++];
                word=(word&~mask)|(t.writedata&mask);
                --write_left;
            }
        }
        t.clk=1; t.eval(); ++cycles;
        if (inhibit_left) --inhibit_left;
        if (a_accept) { if (t.a_read) ether_wait=true; else ++ether; }
        if (a_valid) { ether_wait=false; ++ether; }
        if (cycles>300000) throw std::runtime_error("Timeout");
        return s;
    }
    void transfer(unsigned count,unsigned id) {
        unsigned base=0x2180000+id*512;
        t.source_address=base; t.source_burstcount=count; t.source_read=0; t.source_write=1;
        unsigned sent=0;
        while (sent<count) {
            auto w=pattern(id,sent);
            for (int k=0;k<4;++k) t.source_writedata[k]=w[k];
            t.source_byteenable=uint16_t(0x5a3c^(sent*977+id*39));
            for (unsigned h=0;h<2;++h) {
                uint64_t data=uint64_t(w[h*2])|(uint64_t(w[h*2+1])<<32), mask=0;
                for (unsigned b=0;b<8;++b) if ((t.source_byteenable>>(h*8+b))&1) mask|=0xffull<<(b*8);
                expected[base*2+sent*2+h]=data&mask;
            }
            if (step().source_accept) ++sent;
        }
        t.source_write=0;
        for (unsigned i=0;i<count*2;++i) if (memory[base*2+i]!=expected[base*2+i]) throw std::runtime_error("Write lanes/byte enables");
        t.source_read=1;
        unsigned received=0;
        while (received<count) {
            auto s=step();
            if (s.source_accept) t.source_read=0;
            if (s.valid) {
                for (unsigned h=0;h<2;++h) {
                    uint64_t data=uint64_t(s.data[h*2])|(uint64_t(s.data[h*2+1])<<32);
                    if (data!=expected[base*2+received*2+h]) throw std::runtime_error("Read packing/order");
                }
                ++received;
            }
        }
    }
};
int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Sim s;
        s.t.inhibit=0; s.t.source_read=0; s.t.source_write=0;
        unsigned id=0;
        for (unsigned repeat=0;repeat<8;++repeat)
            for (unsigned n:{1,16,63,64,65,127,128,160,255}) s.transfer(n,++id);
        std::cout<<"PASS 64-bit DDRAM: 72 read/write pairs, stalls, byte enables, split bursts; "
                 <<s.ether<<" Ethernet transactions, "<<s.commands<<" DDR commands, "<<s.resets<<" burst drain resets\n";
    } catch (const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; }
}
