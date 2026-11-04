// PCM 48 kHz stereo -> activity and fundamental frequency. Frames never reach disk.
export function features(pcm) {
  const n=Math.floor(pcm.length/24), mono=new Float64Array(n);
  for(let i=0;i<n;i++) mono[i]=(pcm.readInt16LE(i*24)+pcm.readInt16LE(i*24+2))/65536;
  let energy=0;
  for(const v of mono) energy+=v*v;
  const rms=Math.sqrt(energy/Math.max(1,n));
  if(rms<0.012||n<160)return {voiced:false,pitch:null};
  let best=0,lagBest=0;const correlations=[];
  for(let lag=8;lag<=123&&lag<n/2;lag++){
    let dot=0,a=0,b=0;
    for(let i=0;i<n-lag;i++){dot+=mono[i]*mono[i+lag];a+=mono[i]*mono[i];b+=mono[i+lag]*mono[i+lag];}
    const correlation=dot/Math.sqrt(Math.max(1e-20,a*b));
    correlations[lag]=correlation;
    // Find the best repetition, then prefer its first strong local peak.
    if(correlation>best){best=correlation;lagBest=lag;}
  }
  for(let lag=9;lag<correlations.length-1;lag++){if(correlations[lag]>.8&&correlations[lag]>=best-.03&&correlations[lag]>correlations[lag-1]&&correlations[lag]>=correlations[lag+1]){lagBest=lag;break;}}
  return {voiced:true,pitch:best>.65&&lagBest?8000/lagBest:null};
}
