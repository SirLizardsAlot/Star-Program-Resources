// Compare the archived sky with the texture-backed renderer in an isolated GPU.
// This does not start or connect to Minecraft.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';

const here=path.dirname(fileURLToPath(import.meta.url));
const packages=process.env.CODEX_NODE_MODULES??'C:/Users/lylel/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=await import(pathToFileURL(path.join(packages,'playwright/index.mjs')).href);
const input=JSON.parse(execFileSync('py',['-c',String.raw`
import base64,importlib.util,json
from pathlib import Path
from zipfile import ZipFile
root=Path(${JSON.stringify(here)})
def mod(name):
 s=importlib.util.spec_from_file_location(name,root/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
with ZipFile(root.parent/'sp_sky-panels-one-way-mc26.3.zip') as z: old={n:z.read(n) for n in z.namelist()}
data=mod('prepare_data'); patches=data.make_data(); patches.update(mod('patch_shaders').make_shaders(old))
new={**old,**patches}
def text(resources):return {n:b.decode() for n,b in resources.items() if n.endswith('.glsl')}
png=patches['assets/dfsky/textures/effect/sky_data.png'];pixels=data.decode_generated_png(png)
print(json.dumps({'old':text(old),'new':text(new),'png':base64.b64encode(png).decode(),'pixels':base64.b64encode(pixels).decode(),'size':[data.WIDTH,data.HEIGHT]}))
`],{encoding:'utf8',maxBuffer:8*1024*1024}));
function expand(resources,name,stack=[]){
  if(stack.includes(name))throw Error('Recursive shader include: '+name);
  const value=resources[name];if(value===undefined)throw Error('Missing shader resource '+name);
  return value.replace(/^\s*#include\s+<([^:>]+):([^>]+)>\s*$/gm,(_,ns,file)=>expand(resources,`assets/${ns}/shaders/include/${file}`,[...stack,name]));
}
input.oldSky=expand(input.old,'assets/dfsky/shaders/include/sky.glsl');
input.newSky=expand(input.new,'assets/dfsky/shaders/include/sky.glsl');
input.newTime=expand(input.new,'assets/dfsky/shaders/include/runtime.glsl');
input.newSettings=expand(input.new,'assets/dfsky/shaders/include/settings.glsl');
delete input.old;delete input.new;
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  const page=await browser.newPage({viewport:{width:1200,height:900},deviceScaleFactor:1});
  await page.setContent(`<!doctype html><style>*{box-sizing:border-box}body{margin:0;padding:24px;background:#10171e;color:#e4edf3;font:15px Segoe UI,sans-serif}h1{font-size:22px;margin:0 0 8px}p{color:#a9bbc8}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}figure{margin:0;padding:10px;background:#192630;border:1px solid #344854}figcaption{margin-bottom:7px}canvas{display:block;width:100%;height:auto}.pass{color:#9de3b9}</style><h1>Texture-backed sky: appearance comparison</h1><p>The original renderer is compared with texture lookups and shared sky-state calculation in the vertex stage.</p><div class="grid">${[0,6000,13000,18000].flatMap(tick=>['original','texture','atlas'].map(kind=>`<figure><figcaption>${tick} ticks / ${kind}</figcaption><canvas id="${tick}-${kind}" width="256" height="192"></canvas></figure>`)).join('')}</div><p id="result" class="pass"></p><p>Isolated WebGL2 / SwiftShader check. This is not Minecraft or a live game check.</p>`);
  const report=await page.evaluate(async input=>{
    const width=256,height=192,canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
    const gl=canvas.getContext('webgl2',{antialias:false,preserveDrawingBuffer:true,premultipliedAlpha:false});
    if(!gl)throw Error('WebGL2 unavailable');
    const prefix='#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp sampler2D;\n';
    const vertexBody=`out vec3 ray;out vec2 screenUV;uniform mat3 Camera;void main(){vec2 uv=vec2((gl_VertexID<<1)&2,gl_VertexID&2);screenUV=uv;gl_Position=vec4(uv*2.-1.,0.,1.);ray=Camera*vec3((uv*2.-1.)*vec2(1.12,.84),-1.);VERTEX_STATE}`;
    function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
    function program(vs,fs){const start=performance.now(),p=gl.createProgram();gl.attachShader(p,shader(gl.VERTEX_SHADER,vs));gl.attachShader(p,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return{p,compileAndLinkMs:performance.now()-start};}
    const old=program(prefix+vertexBody.replace('VERTEX_STATE',''),prefix+input.oldSky+`in vec3 ray;uniform float Ticks;uniform float Clock;out vec4 fragColor;void main(){dfsky_setTime(Ticks);fragColor=vec4(dfsky_render(ray,Clock),1.);}`);
    const stateOut=`flat out vec4 spSkyA;flat out vec4 spSkyB;flat out vec4 spSkyC;flat out vec4 spSkyD;uniform float Ticks;`;
    const stateAssign=`dfsky_setTime(Ticks);spSkyA=vec4(dfskyState.sunAngle,dfskyState.starBrightness,dfskyState.skyColor.rg);spSkyB=vec4(dfskyState.skyColor.b,dfskyState.fogColor);spSkyC=dfskyState.cloudColor;spSkyD=dfskyState.sunsetColor;`;
    const stateIn=`flat in vec4 spSkyA;flat in vec4 spSkyB;flat in vec4 spSkyC;flat in vec4 spSkyD;`;
    const newer=program(prefix+input.newSettings+input.newTime+stateOut+vertexBody.replace('VERTEX_STATE',stateAssign),prefix+`uniform sampler2D SkyDataSampler;\n#define DFSKY_SAMPLER SkyDataSampler\n`+input.newSky+stateIn+`in vec3 ray;in vec2 screenUV;uniform float Ticks;uniform float Clock;uniform int AtlasMode;uniform vec2 AtlasOrigin;out vec4 fragColor;void main(){if(AtlasMode!=0){float ignored;vec2 point=AtlasOrigin+clamp(screenUV,vec2(0.),vec2(.99999))*16.;if(!dfsky_marker(SkyDataSampler,point/vec2(textureSize(SkyDataSampler,0)),ignored)){fragColor=vec4(1.,0.,1.,1.);return;}}dfskyState=DfSkyState(Ticks,spSkyA.x,spSkyA.y,vec3(spSkyA.zw,spSkyB.x),spSkyB.yzw,spSkyC,spSkyD);fragColor=vec4(dfsky_render(ray,Clock),1.);}`);
    const bytes=text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0));
    const pixels=bytes(input.pixels),[tw,th]=input.size;
    gl.activeTexture(gl.TEXTURE0);gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL,gl.NONE);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
    const dataTexture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,dataTexture);
    const bitmap=await createImageBitmap(await(await fetch('data:image/png;base64,'+input.png)).blob(),{colorSpaceConversion:'none',premultiplyAlpha:'none'});
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,gl.RGBA,gl.UNSIGNED_BYTE,bitmap);
    const texParams=()=>{gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);};texParams();
    const dataFramebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,dataFramebuffer);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,dataTexture,0);
    const uploaded=new Uint8Array(pixels.length);gl.readPixels(0,0,tw,th,gl.RGBA,gl.UNSIGNED_BYTE,uploaded);
    for(let i=0;i<pixels.length;i++)if(pixels[i]!==uploaded[i])throw Error(`PNG GPU upload changed byte ${i}: ${pixels[i]} -> ${uploaded[i]}`);
    const aw=512,ah=256,origin=[48,32],atlasPixels=new Uint8Array(aw*ah*4);
    for(let i=3;i<atlasPixels.length;i+=4)atlasPixels[i]=255;
    for(let y=0;y<th;y++)atlasPixels.set(pixels.subarray(y*tw*4,(y+1)*tw*4),((y+origin[1])*aw+origin[0])*4);
    const atlasTexture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,atlasTexture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,aw,ah,0,gl.RGBA,gl.UNSIGNED_BYTE,atlasPixels);texParams();
    gl.activeTexture(gl.TEXTURE3);const outputTexture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,outputTexture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);texParams();
    const framebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,outputTexture,0);
    if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('Incomplete render framebuffer');
    function camera(yaw,pitch){const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);return new Float32Array([cy,0,-sy,sy*sp,cp,cy*sp,sy*cp,-sp,cy*cp]);}
    function render(record,tick,clock,view,atlas){const p=record.p;gl.useProgram(p);gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.viewport(0,0,width,height);gl.disable(gl.DEPTH_TEST);gl.disable(gl.BLEND);gl.uniformMatrix3fv(gl.getUniformLocation(p,'Camera'),false,view);gl.uniform1f(gl.getUniformLocation(p,'Ticks'),tick);gl.uniform1f(gl.getUniformLocation(p,'Clock'),clock);gl.uniform1i(gl.getUniformLocation(p,'AtlasMode'),atlas?1:0);gl.uniform2fv(gl.getUniformLocation(p,'AtlasOrigin'),origin);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,atlas?atlasTexture:dataTexture);gl.uniform1i(gl.getUniformLocation(p,'SkyDataSampler'),0);gl.drawArrays(gl.TRIANGLES,0,3);gl.finish();const image=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,image);return image;}
    function compare(a,b,label){let maximum=0,different=0;for(let i=0;i<a.length;i++){const d=Math.abs(a[i]-b[i]);maximum=Math.max(maximum,d);if(d)different++;}if(maximum>2)throw Error(`${label}: maximum difference ${maximum}/255 in ${different} channels`);return{maximum,different};}
    function paint(id,pixels){const dest=document.getElementById(id);if(!dest)return;const image=new ImageData(width,height);for(let y=0;y<height;y++)image.data.set(pixels.subarray((height-1-y)*width*4,(height-y)*width*4),y*width*4);dest.getContext('2d').putImageData(image,0,0);}
    const checks=[],angles=[[0,0],[0,.65],[.7,-.35],[1.57,0],[3.14,.6],[-1.2,-.85]],ticks=[0,6000,13000,18000];let maxDifference=0;
    for(const tick of ticks)for(const clock of[0,123])for(let i=0;i<angles.length;i++){
      const view=camera(...angles[i]),original=render(old,tick,clock,view,false),texture=render(newer,tick,clock,view,false),a=compare(original,texture,`sky ${tick}/${clock}/${i}`);maxDifference=Math.max(maxDifference,a.maximum);checks.push({tick,clock,angles:angles[i],...a});
      if(clock===0&&i===0){paint(`${tick}-original`,original);paint(`${tick}-texture`,texture);const atlas=render(newer,tick,clock,view,true),b=compare(original,atlas,`atlas sky ${tick}`);maxDifference=Math.max(maxDifference,b.maximum);paint(`${tick}-atlas`,atlas);checks.push({tick,clock,atlasOrigin:origin,...b});}
    }
    if(gl.getError()!==gl.NO_ERROR)throw Error('GL error after comparison');
    document.getElementById('result').textContent=`Passed ${checks.length} comparisons. Maximum color difference ${maxDifference}/255. PNG upload preserves every source byte.`;
    return{renderer:'isolated WebGL2 / SwiftShader',comparisons:checks.length,pixelsCompared:checks.length*width*height,maximumColorDifference:maxDifference,PNGUploadByteExact:true,dataTextureSize:input.size,atlasMarkerOrigin:origin,flatVertexState:true,oldProgramCompileLinkMs:old.compileAndLinkMs,newProgramCompileLinkMs:newer.compileAndLinkMs,checks,limits:['Not Minecraft, a live game check, or a guarantee for other GPU drivers.','Checks exact sky imagery, vertex-computed selected state and data-atlas lookup.']};
  },input);
  const preview=path.join(here,'cold-load-preview.png');await page.screenshot({path:preview,fullPage:true});
  fs.writeFileSync(path.join(here,'render-check-report.json'),JSON.stringify({...report,preview},null,2)+'\n');
  console.log(JSON.stringify({...report,checks:undefined,preview}));
}finally{await browser.close();}

// Reuse the earlier geometry-based culling check, with its old imagery (shown
// equivalent above) and the actual newly reversed model files. Keep the old
// preview and its historical report intact.
let panelSource=fs.readFileSync(path.join(here,'../panel_back_preview.mjs'),'utf8');
function replaceOne(source,old,replacement){if(source.split(old).length!==2)throw Error('Panel check patch point changed: '+old);return source.replace(old,replacement);}
panelSource=replaceOne(panelSource,"const root=path.dirname(fileURLToPath(import.meta.url)),overrides=path.join(root,'overrides');",`const root=${JSON.stringify(path.resolve(here,'..'))},overrides=${JSON.stringify(path.join(here,'overrides'))};`);
panelSource=replaceOne(panelSource,"const sky=expand('assets/dfsky/shaders/include/sky.glsl');",`const sky=${JSON.stringify(input.oldSky)};`);
panelSource=panelSource.replaceAll('Sky Panel: sky front, transparent tinted-glass rear','Sky Panel: clear exposed side, sky on the mounting side');
panelSource=replaceOne(panelSource,"if(side==='rear'&&(maxRearError!==0||behindVisible<1000))","if(side==='front'&&(maxRearError!==0||behindVisible<1000))");
panelSource=replaceOne(panelSource,"if(side==='front'&&(skyDifference<1000||behindVisible!==0))","if(side==='rear'&&(skyDifference<1000||behindVisible!==0))");
panelSource=replaceOne(panelSource,"if(side==='rear')minRearPixels=Math.min(minRearPixels,behindVisible);else minFrontPixels=Math.min(minFrontPixels,skyDifference);","if(side==='front')minRearPixels=Math.min(minRearPixels,behindVisible);else minFrontPixels=Math.min(minFrontPixels,skyDifference);");
panelSource=replaceOne(panelSource,"maximumDifferenceFromGlassOnly:side==='rear'?maxRearError:undefined","maximumDifferenceFromGlassOnly:side==='front'?maxRearError:undefined");
panelSource=panelSource.replaceAll('Rear views match glass-only output exactly and reveal the room behind.','The former sky side now matches glass-only output exactly. The mounting side shows sky.');
panelSource=panelSource.replaceAll('rearMaximumDifferenceFromGlassOnly:0','frontMaximumDifferenceFromGlassOnly:0').replaceAll('minimumRearBackgroundVisiblePixels:minRearPixels','minimumFrontBackgroundVisiblePixels:minRearPixels').replaceAll('minimumFrontSkyPixels:minFrontPixels','minimumMountingSideSkyPixels:minFrontPixels');
panelSource=panelSource.replaceAll('The rear test compares against the same geometry with its sky face omitted.','The clear-side test compares against the same geometry with its sky face omitted.');
panelSource=panelSource.replaceAll("path.join(root,'panel-back-preview.png')",`path.join(${JSON.stringify(here)},'panel-orientation-preview.png')`).replaceAll("path.join(root,'panel-back-preview-report.json')",`path.join(${JSON.stringify(here)},'panel-orientation-report.json')`);
console.log(execFileSync(process.execPath,['--input-type=module'],{input:panelSource,encoding:'utf8',maxBuffer:2*1024*1024}).trim());
