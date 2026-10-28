# SimReady assets on the web (three.js and other glTF viewers)

Browsers can't load USD, so convert to `.glb` with the `convert_to_glb` MCP tool or `simready convert`. The output is
**Y-up, meters**, textures embedded, one node per mesh with world transforms baked in.

## Size budget: decide before converting

SimReady textures are 2K–4K PNG (8 MB each is normal). A raw conversion of a conveyor is ~60 MB.
For the web, always cap texture size and use JPEG (`simready convert --max-tex N --jpeg`; MCP tool args `max_tex`, `jpeg`):

Measured on conveyor_belt_a02 (290k triangles, 19 textures):

| Use | Command | Size |
|---|---|---|
| raw (don't ship this) | no flags | 59 MB |
| Hero object, close-up | `--max-tex 2048 --jpeg` | 16 MB |
| Normal scene prop | `--max-tex 1024 --jpeg` | 11 MB |
| Low textures only | `--max-tex 512 --jpeg` | 9.8 MB ← geometry now dominates |
| + meshopt compression | gltf-transform `--compress meshopt` | 1.6 MB |
| + simplify to 25 % | `--simplify-ratio 0.25 --simplify-error 0.001` | 1.1 MB |

Triangle counts are simulation-grade, so after texture downscaling the geometry is the bulk.
Compress (and optionally simplify) with gltf-transform (needs Node.js):

```bash
npx -y @gltf-transform/cli@4.1.1 optimize in.glb out.glb --compress meshopt --texture-compress false
# more aggressive: add  --simplify-ratio 0.25 --simplify-error 0.001   (check the look afterwards)
npx -y @gltf-transform/cli@4.1.1 validate out.glb      # should report "No errors found"
```
Keep `--texture-compress false`: the converter already did JPEG + resize, and the webp path
needs the `sharp` native module, which often fails on Windows ("colourspace: parameter space not set").
`--compress meshopt` needs `MeshoptDecoder` on the three.js side (below). `draco` also works
with `DRACOLoader`. Tangent-space warnings from the validator are harmless (three.js derives tangents).

## Loading in three.js

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
const scene = new THREE.Scene();
// PBR metal/plastic looks flat without an environment map
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment()).texture;

const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const { scene: conveyor } = await loader.loadAsync('assets/conveyor_belt_a02.glb');
conveyor.traverse(o => { if (o.isMesh) { o.castShadow = o.receiveShadow = true; } });
conveyor.position.set(0, 0, 0);      // units are meters, Y-up
scene.add(conveyor);
```

Placement tip: positions in the GLB are the asset's original pivot (usually the floor-center
of the object), so `position.y = 0` puts it on the floor.

For many copies of the same prop (pallets, boxes, bolts), load once and `clone()` the scene,
or merge into `InstancedMesh` for hundreds of copies.

## Physics on the web

glTF has no physics, so colliders/mass are dropped. Use a web physics engine (Rapier, cannon-es)
with simple box/convex colliders from the object's bounding box. The converter prints the size in
meters, and the USD material physics hints (density, friction) can be copied by hand if realism matters.

## React Three Fiber

```jsx
import { useGLTF } from '@react-three/drei';
function Conveyor(props) {
  const { scene } = useGLTF('/assets/conveyor_belt_a02.glb');
  return <primitive object={scene.clone()} {...props} />;
}
```
`npx gltfjsx model.glb --transform` also works on the converted files.

## Attribution

CC-BY-4.0: show a credit such as
"3D assets: NVIDIA SimReady Assets (CC BY 4.0), converted to glTF" in the page footer or credits.
