import test from 'node:test';
import assert from 'node:assert/strict';
import {features} from './dsp.mjs';
test('silence is not sung and a sine produces an octave-equivalent pitch',()=>{
 assert.deepEqual(features(Buffer.alloc(19200)),{voiced:false,pitch:null});
 const pcm=Buffer.alloc(19200);
 for(let i=0;i<4800;i++){const v=Math.round(12000*Math.sin(2*Math.PI*220*i/48000));pcm.writeInt16LE(v,i*4);pcm.writeInt16LE(v,i*4+2);}
 const result=features(pcm);
 assert.equal(result.voiced,true);
 const cents=Math.abs(1200*Math.log2(result.pitch/220))%1200;
 assert.ok(Math.min(cents,1200-cents)<100);
});

test('the installed Opus decoder produces real PCM for server-side analysis',async()=>{
 const {default:prism}=await import('prism-media');
 const {Readable}=await import('node:stream');
 const {once}=await import('node:events');
 const pcm=Buffer.alloc(19200);
 for(let i=0;i<4800;i++){const v=Math.round(12000*Math.sin(2*Math.PI*220*i/48000));pcm.writeInt16LE(v,i*4);pcm.writeInt16LE(v,i*4+2);}
 const encoder=new prism.opus.Encoder({rate:48000,channels:2,frameSize:960});
 const decoder=new prism.opus.Decoder({rate:48000,channels:2,frameSize:960});
 const chunks=[];
 decoder.on('data',chunk=>chunks.push(chunk));
 const finished=once(decoder,'end');
 Readable.from([pcm]).pipe(encoder).pipe(decoder);
 await finished;
 assert.equal(Buffer.concat(chunks).length,pcm.length);
 assert.equal(features(Buffer.concat(chunks)).voiced,true);
});
