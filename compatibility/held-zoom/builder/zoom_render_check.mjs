// Exercise actual zoom GLSL against an independently narrowed camera projection.
// Local CPU / WebGL checks only. No game, plot connection, or publication.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..');
const packages=process.env.CODEX_NODE_MODULES??'C:/Users/lylel/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=await import(pathToFileURL(path.join(packages,'playwright/index.mjs')).href);
const packArg=process.argv.indexOf('--pack'),pack=packArg<0?null:path.resolve(process.argv[packArg+1]);
const input=JSON.parse(execFileSync('py',['-3','-c',String.raw`
import hashlib,importlib.util,json,re
from pathlib import Path
from zipfile import ZipFile
root=Path(${JSON.stringify(root)});here=Path(${JSON.stringify(here)});pack=${pack?`Path(${JSON.stringify(pack)})`:'None'}
spec=importlib.util.spec_from_file_location('zoom_patch',here/'patch_zoom.py');patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
with ZipFile(root/'sp_sky-panel-clean-face-mc26.3.zip') as z:base={n:z.read(n) for n in z.namelist()}
generated=patch.make_zoom(base)
if pack:
 with ZipFile(pack) as z:
  assert all(z.read(n)==v for n,v in generated.items()),'Generated zoom source differs from final ZIP'
  resources={n:z.read(n) for n in generated}
 archive={'pack':pack.name,'packSHA256':hashlib.sha256(pack.read_bytes()).hexdigest(),'generatedResourcesByteMatchFinalZIP':True}
else:
 resources=generated;archive={'generatedResourcesByteMatchFinalZIP':False,'source':'make_zoom output over pinned clean-face pack'}
vertex=resources[patch.POST_VERTEX].decode();fragment=resources[patch.POST_FRAGMENT].decode()
assert 'spCrop = spZoomCropFactor(spProjectionScale().y, readChannel(ZOOM_AMOUNT));' in vertex
uv=re.search(r'texCoord = ([^;]+);',fragment)[1]
assert uv=='vec2(0.5) + (baseTexCoord - vec2(0.5)) * spCrop'
assert 'spRecoil' not in vertex+fragment
print(json.dumps({'helper':resources[patch.HELPER].decode(),'uvExpression':uv,'archiveAudit':archive,'resourceHashes':{n:hashlib.sha256(v).hexdigest() for n,v in resources.items()}}))
`],{encoding:'utf8',maxBuffer:2*1024*1024}));
input.cases=[];
for(const fov of[30,70,110])for(const amount of[0,.25,.5,.75,.99,1]){
  const nativeY=1/Math.tan(fov*Math.PI/360),expectedFov=fov*(1-amount);
  input.cases.push({fov,amount,nativeY,expectedFov,wireByte:Math.round(amount*255),wireAmount:Math.round(amount*255)/255});
}
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  const page=await browser.newPage({viewport:{width:1370,height:1270},deviceScaleFactor:1});
  await page.setContent(`<style>*{box-sizing:border-box}body{background:#10171e;color:#dfeaf2;font:15px Segoe UI;margin:20px}h1{font-size:22px;margin:0 0 8px}.grid{display:grid;grid-template-columns:repeat(6,210px);gap:10px}figure{background:#192630;padding:7px;margin:0;border:1px solid #344854}canvas{width:194px;height:109px;display:block}figcaption{margin-bottom:5px;font-size:12px}p{color:#a5b6c4}.pass{color:#9ce3b7}</style><h1>Held zoom: angular FOV and centered projection</h1><p>Each pair of rows compares the actual post crop with an independently narrowed camera. Zoom strength holds the center and preserves aspect.</p><div class="grid">${[30,70,110].flatMap(fov=>['post','camera'].flatMap(mode=>[0,.25,.5,.75,.99,1].map(t=>`<figure><figcaption>${fov}° / ${100*t}% / ${mode}</figcaption><canvas id="${fov}-${t}-${mode}" width="320" height="180"></canvas></figure>`))).join('')}</div><p class="pass" id="result"></p><p id="precision"></p><p>At 100%, the source center becomes a uniform image. Post zoom magnifies existing pixels. Direct camera rendering can resolve finer details.</p><p>Isolated WebGL2 / SwiftShader. Analytical hallway surfaces isolate perspective behavior. This is not Minecraft.</p>`);
  const report=await page.evaluate(input=>{
    const w=320,h=180,aspect=w/h,canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
    const gl=canvas.getContext('webgl2',{antialias:false,premultipliedAlpha:false,preserveDrawingBuffer:true});if(!gl)throw Error('WebGL2 unavailable');
    const prefix='#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n';
    function shader(type,text){const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
    function program(v,f,feedback){const p=gl.createProgram();gl.attachShader(p,shader(gl.VERTEX_SHADER,prefix+v));gl.attachShader(p,shader(gl.FRAGMENT_SHADER,prefix+f));if(feedback)gl.transformFeedbackVaryings(p,['spCrop','ProbeUV'],gl.INTERLEAVED_ATTRIBS);gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return p;}
    const fullscreen='out vec2 uv;void main(){uv=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(uv*2.-1.,0.,1.);}';
    const scene=`
      vec3 hallway(vec3 direction){
        vec3 origin=vec3(.2,1.6,.3),d=normalize(direction);float distance=1e6;int face=0;
        if(d.y<-.00001){float t=-origin.y/d.y;if(t<distance){distance=t;face=1;}}
        if(d.y>.00001){float t=(4.-origin.y)/d.y;if(t<distance){distance=t;face=2;}}
        if(d.x<-.00001){float t=(-3.-origin.x)/d.x;if(t<distance){distance=t;face=3;}}
        if(d.x>.00001){float t=(3.-origin.x)/d.x;if(t<distance){distance=t;face=4;}}
        if(d.z<-.00001){float t=(-24.-origin.z)/d.z;if(t<distance){distance=t;face=5;}}
        vec3 hit=origin+d*distance;vec2 plane=face<3?hit.xz:face<5?hit.zy:hit.xy;
        vec2 cell=fract(plane),edge=min(cell,1.-cell),aa=max(fwidth(plane),vec2(.002));
        vec2 line=1.-smoothstep(vec2(.018),vec2(.018)+aa,edge);
        float checker=mod(floor(plane.x)+floor(plane.y),2.);
        vec3 color=face==1?mix(vec3(.19,.23,.27),vec3(.34,.39,.43),checker):face==2?vec3(.36,.40,.43):face==5?vec3(.23,.36,.43):vec3(.49,.42,.31);
        color=mix(color,vec3(.065,.10,.14),max(line.x,line.y)*.85);
        if(face==3||face==4){float band=abs(fract((hit.z+1.)/5.)-.5);float panel=(1.-smoothstep(.29,.32,band))*smoothstep(.6,.7,hit.y)*(1.-smoothstep(2.7,2.8,hit.y));color=mix(color,face==3?vec3(.12,.35,.50):vec3(.50,.24,.14),panel*.8);}
        // A wide, solid center marker also makes the 100% limit unambiguous.
        if(face==5){float mark=(1.-smoothstep(.16,.19,abs(hit.x-.2)))*(1.-smoothstep(.55,.6,abs(hit.y-1.6)));color=mix(color,vec3(.95,.80,.19),mark);}
        return color*(.45+.55*exp(-distance*.015));
      }
    `;
    const direct=program(fullscreen,`in vec2 uv;uniform vec2 TangentHalfFov;uniform int RayField;out vec4 color;${scene}void main(){vec3 ray=vec3((uv*2.-1.)*TangentHalfFov,-1.);color=vec4(RayField!=0?normalize(ray)*.5+.5:hallway(ray),1.);}`);
    const mapping=input.uvExpression;
    const post=program(input.helper+`\nout vec2 baseTexCoord;flat out float spCrop;out vec2 ProbeUV;uniform float ProjectionY;uniform float Strength;uniform vec2 Probe;void main(){baseTexCoord=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(baseTexCoord*2.-1.,0.,1.);spCrop=spZoomCropFactor(ProjectionY,Strength);vec2 saved=baseTexCoord;baseTexCoord=Probe;ProbeUV=${mapping};baseTexCoord=saved;}`,
      `in vec2 baseTexCoord;flat in float spCrop;uniform sampler2D Source;out vec4 color;void main(){vec2 texCoord=${mapping};color=texture(Source,texCoord);}`,true);
    function target(){const texture=gl.createTexture();gl.activeTexture(gl.TEXTURE3);gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,w,h,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);const fbo=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,texture,0);return{texture,fbo};}
    const source=target(),output=target();gl.viewport(0,0,w,h);gl.disable(gl.BLEND);gl.disable(gl.DEPTH_TEST);
    function pixels(){const value=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,value);return value;}
    function renderDirect(fov,field=false,target=output){gl.bindFramebuffer(gl.FRAMEBUFFER,target.fbo);gl.useProgram(direct);const tan=Math.tan(fov*Math.PI/360);gl.uniform2fv(gl.getUniformLocation(direct,'TangentHalfFov'),[tan*aspect,tan]);gl.uniform1i(gl.getUniformLocation(direct,'RayField'),field?1:0);gl.drawArrays(gl.TRIANGLES,0,3);return pixels();}
    function setupPost(test,amount=test.amount,probe=[.5,.5]){gl.useProgram(post);const loc=n=>gl.getUniformLocation(post,n);gl.uniform1f(loc('ProjectionY'),test.nativeY);gl.uniform1f(loc('Strength'),amount);gl.uniform2fv(loc('Probe'),probe);gl.uniform1i(loc('Source'),0);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,source.texture);}
    function renderPost(test){gl.bindFramebuffer(gl.FRAMEBUFFER,output.fbo);setupPost(test);gl.drawArrays(gl.TRIANGLES,0,3);return pixels();}
    const feedback=gl.createTransformFeedback(),feedbackBuffer=gl.createBuffer();
    function probe(test,amount=test.amount,point=[.5,.5]){setupPost(test,amount,point);gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK,feedback);gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER,feedbackBuffer);gl.bufferData(gl.TRANSFORM_FEEDBACK_BUFFER,36,gl.STREAM_READ);gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER,0,feedbackBuffer);gl.enable(gl.RASTERIZER_DISCARD);gl.beginTransformFeedback(gl.TRIANGLES);gl.drawArrays(gl.TRIANGLES,0,3);gl.endTransformFeedback();gl.disable(gl.RASTERIZER_DISCARD);const data=new Float32Array(9);gl.getBufferSubData(gl.TRANSFORM_FEEDBACK_BUFFER,0,data);gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER,0,null);gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK,null);return{crop:data[0],uv:[data[1],data[2]]};}
    function difference(a,b){let maximum=0,sum=0,aboveTwo=0;for(let i=0;i<a.length;i++)if(i%4!==3){const d=Math.abs(a[i]-b[i]);sum+=d;maximum=Math.max(maximum,d);if(d>2)aboveTwo++;}return{maximum,mean:sum/(w*h*3),channelsAboveTwo:aboveTwo};}
    function uniformDifference(data){let maximum=0;for(let i=4;i<data.length;i++)maximum=Math.max(maximum,Math.abs(data[i]-data[i%4]));return maximum;}
    function paint(id,data){const dest=document.getElementById(id),result=new ImageData(w,h);for(let y=0;y<h;y++)result.data.set(data.subarray((h-y-1)*w*4,(h-y)*w*4),y*w*4);dest.getContext('2d').putImageData(result,0,0);}
    const checks=[];let maxRay=0,maxCrop=0,maxUV=0,maxIdentity=0,maxUniform=0,maxWireCrop=0;
    for(const test of input.cases){
      const measured=probe(test),expectedCrop=Math.tan(test.expectedFov*Math.PI/360)*test.nativeY;
      if(!Number.isFinite(measured.crop)||measured.crop<0||measured.crop>1)throw Error('Invalid GLSL crop');
      if(test.amount===0&&measured.crop!==1||test.amount===1&&measured.crop!==0)throw Error('Zoom endpoint is not exact');
      if(measured.uv[0]!==.5||measured.uv[1]!==.5)throw Error('Zoom center moved');
      const cropError=Math.abs(measured.crop-expectedCrop);if(cropError>.0005)throw Error('Angular-FOV crop differs from physical reference');maxCrop=Math.max(maxCrop,cropError);
      let uvError=0;
      for(const point of[[0,0],[1,0],[0,1],[1,1],[.25,.75]]){
        const observed=probe(test,test.amount,point).uv,expected=point.map(v=>.5+(v-.5)*measured.crop);
        if(observed.some(v=>!Number.isFinite(v)||v<0||v>1))throw Error('UV is outside source or non-finite');
        uvError=Math.max(uvError,...observed.map((v,i)=>Math.abs(v-expected[i])));
      }
      if(uvError>1e-7)throw Error('Horizontal and vertical zoom factors differ');maxUV=Math.max(maxUV,uvError);
      const wire=probe(test,test.wireAmount),expectedWire=Math.tan(test.fov*(1-test.wireAmount)*Math.PI/360)*test.nativeY;
      const wireError=Math.abs(wire.crop-expectedWire);if(wireError>.0005)throw Error('Quantized control crop differs from angular reference');maxWireCrop=Math.max(maxWireCrop,wireError);
      const original=renderDirect(test.fov,false,source),actual=renderPost(test),camera=renderDirect(test.expectedFov),sceneDifference=difference(actual,camera);
      let identityError,uniformError;
      if(test.amount===0){identityError=difference(actual,original).maximum;maxIdentity=Math.max(maxIdentity,identityError);if(identityError!==0)throw Error('Zero zoom is not exact identity');}
      if(test.amount===1){uniformError=uniformDifference(actual);maxUniform=Math.max(maxUniform,uniformError);if(uniformError!==0)throw Error('100% zoom is not uniform source center');}
      paint(test.fov+'-'+test.amount+'-post',actual);paint(test.fov+'-'+test.amount+'-camera',camera);
      renderDirect(test.fov,true,source);const rayPost=renderPost(test),rayCamera=renderDirect(test.expectedFov,true),rayDifference=difference(rayPost,rayCamera);
      if(rayDifference.maximum>2)throw Error('Zoom does not match the narrowed camera ray field: '+JSON.stringify({test,rayDifference}));maxRay=Math.max(maxRay,rayDifference.maximum);
      checks.push({...test,compiledCrop:measured.crop,expectedCrop,cropError,centerUV:measured.uv,uvMaximumError:uvError,wireCompiledCrop:wire.crop,wireCropError:wireError,sceneDifference,rayFieldDifference:rayDifference,identityMaximumDifference:identityError,uniformMaximumDifference:uniformError});
    }
    if(gl.getError()!==gl.NO_ERROR)throw Error('GL zoom check error');
    document.getElementById('result').textContent=`Passed ${checks.length} FOV / zoom cases. Same-FOV camera rays match within ${maxRay}/255. Zero zoom is byte-exact identity. 100% zoom is exactly uniform.`;
    document.getElementById('precision').textContent=`Center stays exactly (0.5, 0.5). Equal-axis mapping error ${maxUV.toExponential(2)}. GLSL angular crop error ${maxCrop.toExponential(2)}.`;
    return{renderer:'isolated WebGL2 / SwiftShader',cases:checks.length,rayFieldPixelsCompared:checks.length*w*h,maximumRayFieldColorDifference:maxRay,maximumCropError:maxCrop,maximumQuantizedControlCropError:maxWireCrop,maximumCenteredUniformAxisMappingError:maxUV,centerExact:true,zeroZoomMaximumDifference:maxIdentity,fullZoomUniformMaximumDifference:maxUniform,finiteCropAndUV:true,checks};
  },input);
  const preview=path.join(here,'zoom-preview.png');await page.screenshot({path:preview,fullPage:true});
  const final={...input.archiveAudit,actualGLSLResourceHashes:input.resourceHashes,angularFovFormula:'targetVerticalFov = currentVerticalFov * (1 - strength)',...report,limits:['Analytical hallway plus smooth ray-field reference. No Minecraft or full effect stack was run.','Scene image differences include magnifying existing source pixels versus rendering fresh details at the narrower camera FOV. The smooth ray field checks projection separately.','Byte controls quantize strength in 1/255 steps. Existing data-pass smoothing can produce intermediate strengths tested directly by the helper.'],preview};
  fs.writeFileSync(path.join(here,'zoom-render-report.json'),JSON.stringify(final,null,2)+'\n');
  console.log(JSON.stringify({...final,checks:undefined}));
}finally{await browser.close();}
