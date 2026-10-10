#include "Vtv_ddr_arbiter.h"
#include "verilated.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <cstdint>

struct Master { bool active=false,reading=false,command=false; unsigned count=0,sent=0,received=0,address=0; };
int main(int argc,char**argv) {
    Verilated::commandArgs(argc,argv);Vtv_ddr_arbiter d;Master a,b;
    unsigned rng=0x1234,reads=0,writes=0,read_rem=0,read_addr=0,read_i=0,delay=0;
    unsigned write_rem=0,write_addr=0,write_i=0,write_count=0;
    unsigned a_base=0x2000000,b_base=0x2180000,transactions=0,resets=0,masked=0;
    auto random=[&](){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;};
    auto fail=[](const char*s){throw std::runtime_error(s);};
    try {
        for(unsigned c=0;c<200000;c++) {
            d.clk=0;bool reset=(c%997)>=910&&(c%997)<930;d.inhibit=reset;
            if(reset) {a={};if(c%997==910)++resets;}
            auto prepare=[&](Master&m,unsigned base) {
                if(!m.active) {m.active=true;m.reading=(random()&1);m.count=(random()&1)?16:32;
                    m.sent=0;m.received=0;m.command=false;m.address=base+(random()&1023)*64;}
            };
            if(!reset)prepare(a,a_base);prepare(b,b_base);
            d.a_read=a.active&&a.reading&&!a.command;d.a_write=a.active&&!a.reading;
            d.b_read=b.active&&b.reading&&!b.command;d.b_write=b.active&&!b.reading;
            d.a_address=a.address;d.a_burstcount=a.count;d.a_byteenable=65535;
            d.b_address=b.address;d.b_burstcount=b.count;d.b_byteenable=65535;
            for(int k=0;k<4;k++){d.a_writedata[k]=a.address+a.sent+k;d.b_writedata[k]=b.address+b.sent+k;}
            d.waitrequest=(random()%7)==0;d.readdatavalid=0;
            if(read_rem) {
                if(delay)--delay;
                else if(random()%3) {d.readdatavalid=1;for(int k=0;k<4;k++)d.readdata[k]=read_addr+read_i+k;}
            }
            d.eval();
            auto response=[&](Master&m,bool valid,const auto&data) {
                if(!valid)return;
                if(!m.active||!m.reading||!m.command)fail("response to idle or wrong master");
                for(int k=0;k<4;k++)if(data[k]!=m.address+m.received+k)fail("misordered/misrouted read data");
                if(++m.received==m.count){m.active=false;++transactions;}
            };
            response(a,d.a_readdatavalid,d.a_readdata);response(b,d.b_readdatavalid,d.b_readdata);
            if(d.read&&!d.waitrequest) {
                if(read_rem||write_rem)fail("overlapping bursts");
                read_addr=d.address;read_rem=d.burstcount;read_i=0;delay=random()%53;++reads;
            }
            if(d.write&&!d.waitrequest) {
                if(read_rem)fail("write while read response outstanding");
                if(!write_rem){write_rem=d.burstcount;write_count=d.burstcount;write_addr=d.address;write_i=0;++writes;}
                if(d.address!=write_addr||d.burstcount!=write_count)fail("write burst header changed");
                if(!d.byteenable)++masked;
                else for(int k=0;k<4;k++)if(d.writedata[k]!=write_addr+write_i+k)fail("lost write beat on arbitration");
                --write_rem;++write_i;
            }
            if(d.readdatavalid){--read_rem;++read_i;}
            auto accept=[&](Master&m,bool wait) {
                if(wait||!m.active)return;
                if(m.reading&&!m.command)m.command=true;
                else if(!m.reading&&++m.sent==m.count){m.active=false;++transactions;}
            };
            accept(a,d.a_waitrequest);accept(b,d.b_waitrequest);
            d.clk=1;d.eval();
        }
        if(reads<100||writes<100||masked<10)fail("insufficient reset/burst coverage");
        std::cout<<"PASS DDR arbiter transactions="<<transactions<<" read_bursts="<<reads<<" write_bursts="<<writes
                 <<" resets="<<resets<<" masked_drain_beats="<<masked<<std::endl;
    }catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<std::endl;return 1;}
}
