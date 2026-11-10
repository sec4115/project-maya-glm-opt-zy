// Real kernels on both devices: mapped input/output must match explicit copies.
#include "strata/kernels/glm_fast.hpp"
#include "strata/core/cpu_lane_plan.hpp"
#include <cuda_runtime.h>
#include <cstdio>
#include <cstring>
#include <vector>

#define CHECK(x) do { cudaError_t e=(x); if(e!=cudaSuccess) { std::fprintf(stderr,"%s: %s\n",#x,cudaGetErrorString(e));return 1;} } while(0)
int main() {
    using namespace strata::core;
    if (!valid_cpu_lane_plan("012233445") || valid_cpu_lane_plan("012") ||
        valid_cpu_lane_plan("112233445") || valid_cpu_lane_plan("012345679")) return 2;
    std::array<double,9> batch{};
    auto fallback=cpu_lane_plan(0.2,0.5,batch);
    CpuLaneCosts costs{};
    if(cpu_lane_joint_plan(costs,8,fallback)!=fallback) return 3;
    for(int f=1;f<=8;++f) for(int k=0;k<=f;++k) costs[f][k]=1.0+(k==f?0.0:0.5);
    auto all=cpu_lane_joint_plan(costs,8,fallback);
    for(int f=1;f<=8;++f) if(((all>>(4*f))&15ull)!=(unsigned long long)f) return 4;
    int devices=0; CHECK(cudaGetDeviceCount(&devices));
    if(devices<2) return 5;
    namespace gf=strata::kernels::glmf;
    constexpr int E=4096,N=32;
    for(int dev=0;dev<2;++dev) {
        CHECK(cudaSetDevice(dev));
        cudaStream_t stream;CHECK(cudaStreamCreateWithFlags(&stream,cudaStreamNonBlocking));
        float *host=nullptr,*mapped=nullptr,*input=nullptr,*a=nullptr,*b=nullptr;
        int *token_h=nullptr,*token_hd=nullptr,*token_d=nullptr,*keys_h=nullptr,*keys_hd=nullptr,*keys_d=nullptr;
        unsigned long long *values_h=nullptr,*values_hd=nullptr,*values_d=nullptr,*ta=nullptr,*tb=nullptr;
        CHECK(cudaHostAlloc((void**)&host,E*sizeof(float),cudaHostAllocMapped));
        CHECK(cudaHostGetDevicePointer((void**)&mapped,host,0));
        CHECK(cudaHostAlloc((void**)&token_h,sizeof(int),cudaHostAllocMapped));
        CHECK(cudaHostGetDevicePointer((void**)&token_hd,token_h,0));
        CHECK(cudaHostAlloc((void**)&keys_h,N*sizeof(int),cudaHostAllocMapped));
        CHECK(cudaHostGetDevicePointer((void**)&keys_hd,keys_h,0));
        CHECK(cudaHostAlloc((void**)&values_h,N*sizeof(unsigned long long),cudaHostAllocMapped));
        CHECK(cudaHostGetDevicePointer((void**)&values_hd,values_h,0));
        CHECK(cudaMalloc((void**)&input,E*sizeof(float)));
        CHECK(cudaMalloc((void**)&a,4*E*sizeof(float)));CHECK(cudaMalloc((void**)&b,4*E*sizeof(float)));
        CHECK(cudaMalloc((void**)&token_d,sizeof(int)));
        CHECK(cudaMalloc((void**)&keys_d,N*sizeof(int)));CHECK(cudaMalloc((void**)&values_d,N*sizeof(unsigned long long)));
        CHECK(cudaMalloc((void**)&ta,N*sizeof(unsigned long long)));CHECK(cudaMalloc((void**)&tb,N*sizeof(unsigned long long)));
        std::vector<float> ha(4*E),hb(4*E);
        std::vector<unsigned long long> hta(N),htb(N);
        for(int round=0;round<256;++round) {
            for(int i=0;i<E;++i) host[i]=(float)((i*37+round*13)%10007)/10007.0f;
            const int peak=(round*17)%E;host[peak]=2.0f;
            for(int i=0;i<N;++i) { keys_h[i]=(i+round)%N;values_h[i]=0x12340000ull+round*N+i; }
            CHECK(cudaMemcpyAsync(input,host,E*sizeof(float),cudaMemcpyHostToDevice,stream));
            gf::embed_streams(input,a,E,stream);gf::embed_streams(mapped,b,E,stream);
            gf::argmax(input,E,token_d,stream);gf::argmax(mapped,E,token_hd,stream);
            CHECK(cudaMemcpyAsync(keys_d,keys_h,N*sizeof(int),cudaMemcpyHostToDevice,stream));
            CHECK(cudaMemcpyAsync(values_d,values_h,N*sizeof(unsigned long long),cudaMemcpyHostToDevice,stream));
            gf::tab_update(ta,keys_d,values_d,N,stream);gf::tab_update(tb,keys_hd,values_hd,N,stream);
            CHECK(cudaStreamSynchronize(stream));
            int token=-1;CHECK(cudaMemcpy(&token,token_d,sizeof(int),cudaMemcpyDeviceToHost));
            CHECK(cudaMemcpy(ha.data(),a,ha.size()*sizeof(float),cudaMemcpyDeviceToHost));
            CHECK(cudaMemcpy(hb.data(),b,hb.size()*sizeof(float),cudaMemcpyDeviceToHost));
            CHECK(cudaMemcpy(hta.data(),ta,N*sizeof(unsigned long long),cudaMemcpyDeviceToHost));
            CHECK(cudaMemcpy(htb.data(),tb,N*sizeof(unsigned long long),cudaMemcpyDeviceToHost));
            if(token!=peak || token_h[0]!=peak || ha!=hb || hta!=htb) return 6;
        }
        CHECK(cudaFree(input));CHECK(cudaFree(a));CHECK(cudaFree(b));CHECK(cudaFree(token_d));
        CHECK(cudaFree(keys_d));CHECK(cudaFree(values_d));CHECK(cudaFree(ta));CHECK(cudaFree(tb));
        CHECK(cudaFreeHost(host));CHECK(cudaFreeHost(token_h));CHECK(cudaFreeHost(keys_h));CHECK(cudaFreeHost(values_h));
        CHECK(cudaStreamDestroy(stream));
        std::printf("CUDA%d mapped embedding/table/token: 256 rounds exact PASS\n",dev);
    }
    return 0;
}
