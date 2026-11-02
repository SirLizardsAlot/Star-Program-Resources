// Test the actual model files and final ZIP, reusing the native-face GPU check.
// No Minecraft process, plot connection, code transfer, or publication.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..');
const archive=path.join(root,'sp_sky-panel-clean-face-mc26.3.zip');
const input=JSON.parse(execFileSync('py',['-3','-c',String.raw`
import hashlib,json
from pathlib import Path
from zipfile import ZipFile
root=Path(${JSON.stringify(root)});here=Path(${JSON.stringify(here)})
new_path=Path(${JSON.stringify(archive)})
assert hashlib.sha256(new_path.read_bytes()).hexdigest()=='f0c2a37afa56fc55040f6d6227426f3b8d5599b1c135c520d0a294fe7329dbed','Frozen pack hash changed'
names=['assets/minecraft/models/block/oak_trapdoor_'+kind+'.json' for kind in ['bottom','top','open']]
with ZipFile(root/'sp_sky-cold-load-mc26.3.zip') as previous, ZipFile(new_path) as current:
 changed=[n for n in previous.namelist() if previous.read(n)!=current.read(n)]
 assert set(previous.namelist())==set(current.namelist()),'Archive paths changed'
 assert set(changed)==set(names),changed
 shaders=[n for n in previous.namelist() if n.endswith(('.vsh','.fsh','.glsl'))]
 assert all(previous.read(n)==current.read(n) for n in shaders),'Shader bytes changed'
 previous_models={n.split('_')[-1][:-5]:json.loads(previous.read(n)) for n in names}
 for name in names:
  data=(here/'overrides'/name).read_bytes()
  assert data==current.read(name),'Model differs from ZIP: '+name
  model=json.loads(data);kind=name.split('_')[-1][:-5]
  sky_face={'bottom':'down','top':'up','open':'south'}[kind]
  glass=model['elements'][0]['faces'];sky=model['elements'][1]['faces']
  assert len(glass)==5 and sky_face not in glass,(name,glass)
  assert list(sky)==[sky_face] and sky[sky_face]['texture']=='#sky',(name,sky)
  assert all(info['texture']=='#glass' for info in glass.values()),name
with ZipFile(root/'sp_sky-panels-one-way-mc26.3.zip') as old:
 def expand(name):
  import re
  return re.sub(r'^\s*#include\s+<([^:>]+):([^>]+)>\s*$',lambda m:expand('assets/'+m[1]+'/shaders/include/'+m[2]),old.read(name).decode(),flags=re.M)
 sky=expand('assets/dfsky/shaders/include/sky.glsl')
print(json.dumps({'sky':sky,'previousModels':previous_models,'audit':{'pack':new_path.name,'sha256':hashlib.sha256(new_path.read_bytes()).hexdigest(),'actualModelFilesByteIdenticalToFinalZIP':True,'changedArchiveEntries':changed,'shaderResourcesByteIdentical':len(shaders),'skyFace':'mounting','glassFacesPerModel':5}}))
`],{encoding:'utf8',maxBuffer:2*1024*1024}));

let source=fs.readFileSync(path.join(root,'panel_back_preview.mjs'),'utf8');
function replaceOne(old,replacement){if(source.split(old).length!==2)throw Error('Native panel test patch point changed: '+old);source=source.replace(old,replacement);}
replaceOne("const root=path.dirname(fileURLToPath(import.meta.url)),overrides=path.join(root,'overrides');",`const root=${JSON.stringify(root)},overrides=${JSON.stringify(path.join(here,'overrides'))};`);
replaceOne("const sky=expand('assets/dfsky/shaders/include/sky.glsl');",`const sky=${JSON.stringify(input.sky)};const previousModels=${JSON.stringify(input.previousModels)};const archiveAudit=${JSON.stringify(input.audit)};`);
replaceOne('async({models,sky,glass,variants})=>{','async({models,previousModels,sky,glass,variants})=>{');
replaceOne('{models,sky,glass:source.glass,variants:source.variants}','{models,previousModels,sky,glass:source.glass,variants:source.variants}');
source=source.replaceAll('Sky Panel: sky front, transparent tinted-glass rear','Sky Panel: pure sky on the mounting face');
source=source.replaceAll("['front','rear'].map(side=>","['front','rear','previous'].map(side=>");
source=source.replaceAll('${kind} / ${side}',"${kind} / ${side==='front'?'exposed glass':side==='rear'?'pure sky':'previous overlay'}");
source=source.replaceAll("repeat(6,1fr)","repeat(3,1fr)");
source=source.replaceAll("width:1200,height:700","width:1200,height:1250");
source=source.replaceAll('Actual generated trapdoor model geometry and native glass texture. Back-face culling is enabled for both sky and glass.','Exposed face stays see-through tinted glass. Mounting face is compared with pure sky. Previous shows the removed glass overlay.');
replaceOne('const checks=[];let minRearPixels=Infinity,minFrontPixels=Infinity;','const checks=[];let minClearPixels=Infinity,minSkyPixels=Infinity,maxSkyOnlyError=0,maxGlassOnlyError=0,minPreviousOverlayPixels=Infinity,maxPreviousOverlayError=0;');
replaceOne('function render(withSky,backgroundVersion){','function render(withSky,backgroundVersion,withGlass=true,geometryModel=model){');
replaceOne('for(const e of model.elements)for(const[face,info]of Object.entries(e.faces)){','for(const e of geometryModel.elements)for(const[face,info]of Object.entries(e.faces)){');
replaceOne('for(const points of glassFaces)quad(points,2);','if(withGlass)for(const points of glassFaces)quad(points,2);');
// Allow a coplanar translucent face to reach the blend stage. This deliberately
// catches the former glass face at exactly the same model coordinate as sky.
replaceOne('gl.depthFunc(gl.LESS);','gl.depthFunc(gl.LEQUAL);');
replaceOne("culling:'BACK, enabled for sky and glass'","culling:'BACK, enabled for sky and glass',depthComparison:'LEQUAL, including coplanar translucent overlays'");
const start=source.indexOf('        const actual=render(true,0),glassOnly=render(false,0),changedBackground=render(true,1);');
const end=source.indexOf("        if((variant.y??0)===0",start);
if(start<0||end<0)throw Error('Native panel comparison block changed');
source=source.slice(0,start)+`        const actual=render(true,0),glassOnly=render(false,0),skyOnly=render(true,0,false),changedBackground=render(true,1),previousOverlay=render(true,0,true,previousModels[kind]);
        let skyDifference=0,behindVisible=0,maxGlassError=0,maxSkyError=0,previousOverlayPixels=0,previousOverlayError=0;
        for(let y=128;y<192;y++)for(let x=128;x<192;x++){
          const i=(y*320+x)*4;let skyDelta=0,backgroundDelta=0,skyOnlyDelta=0,previousDelta=0;
          for(let c=0;c<3;c++){
            skyDelta=Math.max(skyDelta,Math.abs(actual[i+c]-glassOnly[i+c]));
            backgroundDelta=Math.max(backgroundDelta,Math.abs(actual[i+c]-changedBackground[i+c]));
            skyOnlyDelta=Math.max(skyOnlyDelta,Math.abs(actual[i+c]-skyOnly[i+c]));
            previousDelta=Math.max(previousDelta,Math.abs(previousOverlay[i+c]-skyOnly[i+c]));
          }
          if(skyDelta>3)skyDifference++;if(backgroundDelta>3)behindVisible++;
          if(previousDelta>3)previousOverlayPixels++;
          maxGlassError=Math.max(maxGlassError,skyDelta);maxSkyError=Math.max(maxSkyError,skyOnlyDelta);previousOverlayError=Math.max(previousOverlayError,previousDelta);
        }
        if(side==='front'){
          if(maxGlassError!==0||behindVisible<1000)throw Error('Exposed side no longer matches see-through glass: '+state);
          minClearPixels=Math.min(minClearPixels,behindVisible);maxGlassOnlyError=Math.max(maxGlassOnlyError,maxGlassError);
        }else{
          if(maxSkyError!==0||skyDifference<1000||behindVisible!==0)throw Error('Mounting side is not pure sky: '+JSON.stringify({state,maxSkyError,skyDifference,behindVisible}));
          if(previousOverlayPixels<1000)throw Error('Previous glass-overlay regression was not reproduced: '+state);
          minSkyPixels=Math.min(minSkyPixels,skyDifference);maxSkyOnlyError=Math.max(maxSkyOnlyError,maxSkyError);minPreviousOverlayPixels=Math.min(minPreviousOverlayPixels,previousOverlayPixels);maxPreviousOverlayError=Math.max(maxPreviousOverlayError,previousOverlayError);
        }
        checks.push({state,side:side==='front'?'exposed':'mounting',skyDifferencePixels:skyDifference,backgroundVisiblePixels:behindVisible,maximumDifferenceFromGlassOnly:side==='front'?maxGlassError:undefined,maximumDifferenceFromSkyOnly:side==='rear'?maxSkyError:undefined,previousGlassOverlayDifferencePixels:side==='rear'?previousOverlayPixels:undefined,previousGlassOverlayMaximumDifference:side==='rear'?previousOverlayError:undefined});
        if(side==='rear'&&(variant.y??0)===0&&!state.includes('facing=east')&&!state.includes('facing=south')&&!state.includes('facing=west')){
          const dest=document.getElementById(kind+'-previous');if(dest){const image=new ImageData(320,320);for(let y=0;y<320;y++)image.data.set(previousOverlay.subarray((319-y)*320*4,(320-y)*320*4),y*320*4);dest.getContext('2d').putImageData(image,0,0);}
        }
`+source.slice(end);
replaceOne('Rear views match glass-only output exactly and reveal the room behind.','Mounting faces match sky-only output exactly. Exposed faces match see-through glass exactly.');
replaceOne("rearMaximumDifferenceFromGlassOnly:0,minimumRearBackgroundVisiblePixels:minRearPixels,minimumFrontSkyPixels:minFrontPixels","exposedMaximumDifferenceFromGlassOnly:maxGlassOnlyError,mountingMaximumDifferenceFromSkyOnly:maxSkyOnlyError,minimumExposedBackgroundVisiblePixels:minClearPixels,minimumMountingSkyPixels:minSkyPixels,previousOverlayRegressionReproduced:true,minimumPreviousOverlayDifferencePixels:minPreviousOverlayPixels,maximumPreviousOverlayColorDifference:maxPreviousOverlayError");
source=source.replaceAll('The rear test compares against the same geometry with its sky face omitted.','Exposed face uses a glass-only reference. Mounting face uses a sky-only reference. Comparison uses the 64 by 64 face interior.');
source=source.replaceAll('Uses the actual generated models, sky include, and native glass image.','Uses actual ZIP-matched models and native glass texture. Uses the archived sky include already proven pixel-identical to the texture-backed renderer.');
replaceOne("const file=path.join(root,'panel-back-preview.png');",`const file=path.join(${JSON.stringify(here)},'panel-preview.png');`);
replaceOne("path.join(root,'panel-back-preview-report.json')",`path.join(${JSON.stringify(here)},'panel-render-report.json')`);
source=source.replaceAll('{...report,preview:file}','{...report,packSHA256:archiveAudit.sha256,skyMaximumDifferenceFromSkyOnly:report.mountingMaximumDifferenceFromSkyOnly,glassMaximumDifferenceFromGlassOnly:report.exposedMaximumDifferenceFromGlassOnly,archiveAudit,preview:file}');
console.log(execFileSync(process.execPath,['--input-type=module'],{input:source,encoding:'utf8',maxBuffer:2*1024*1024}).trim());
