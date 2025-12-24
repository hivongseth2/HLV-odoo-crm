/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ensureJQuery } from '@web/core/ensure_jquery';
import { ListController } from "@web/views/list/list_controller";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { listView } from "@web/views/list/list_view";

export class Stock3DController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    }

    async open3DView(ev) {
        var self = this;
        await ensureJQuery();
        
        // --- VARIABLES ---
        var wh_data, data;
        let controls, renderer, clock, scene, camera, raycaster;
        let transformControl; 
        var group;
        var wh_id;
        let selectedObject = null;
        let anchorObject = null; 
        let meshMap = {}; 
        
        let floorWidth = 2000;
        let floorDepth = 2000;
        let baseMesh, dragPlane;

        const pointer = new THREE.Vector2();

        // Load Warehouse
        await rpc('/3Dstock/warehouse', { 'company_id': user.context.allowed_company_ids[0] })
            .then(res => { wh_data = res; });
        
        if (!wh_data || wh_data.length === 0) {
            alert("Không tìm thấy kho nào!");
            return;
        }
        wh_id = wh_data[0][0];

        // --- UI CONSTRUCTION ---
        
        // 1. Selector
        const whSelectorDiv = document.createElement("div");
        whSelectorDiv.classList.add("warehouse-selector-container");
        var select = document.createElement("select");
        wh_data.forEach(w => {
            var opt = document.createElement("option");
            opt.value = w[0]; opt.text = w[1];
            select.appendChild(opt);
        });
        select.classList.add("customselect");

        var closeBtn = document.createElement("button");
        closeBtn.classList.add("closeBtn");
        closeBtn.innerHTML = "&times;";
        closeBtn.title = "Thoát";
        closeBtn.onclick = () => window.location.reload();
        
        whSelectorDiv.append(select);
        whSelectorDiv.append(closeBtn);

        // 2. Search Bar
        const searchDiv = document.createElement("div");
        searchDiv.classList.add("search-container");
        searchDiv.style.width = "auto";
        searchDiv.style.gap = "10px";
        searchDiv.innerHTML = `
            <div style="display:flex; align-items:center; background:#f1f1f1; padding:2px 8px; border-radius:15px;">
                <i class="fa fa-map-marker" style="color:#d9534f;"></i>
                <input type="text" id="loc_search_inp" placeholder="Tìm vị trí..." list="loc_datalist" style="border:none; outline:none; background:transparent; margin-left:5px; width:150px; font-size:13px;">
                <datalist id="loc_datalist"></datalist>
                <button id="btn_search_loc" class="btn btn-sm btn-danger" style="border-radius:50%; width:24px; height:24px; padding:0; line-height:24px;"><i class="fa fa-arrow-right"></i></button>
            </div>
            <div style="display:flex; align-items:center; background:#f1f1f1; padding:2px 8px; border-radius:15px;">
                <i class="fa fa-cube" style="color:#007bff;"></i>
                <input type="text" id="product_search_inp" placeholder="Tìm sản phẩm..." style="border:none; outline:none; background:transparent; margin-left:5px; width:150px; font-size:13px;">
                <button id="btn_search_prod" class="btn btn-sm btn-primary" style="border-radius:50%; width:24px; height:24px; padding:0; line-height:24px;"><i class="fa fa-arrow-right"></i></button>
            </div>
        `;

        // 3. Legend
        const legendDiv = document.createElement("div");
        legendDiv.classList.add("legend-container");
        legendDiv.innerHTML = `
            <div class="legend-item"><div class="color-box bg-red"></div>Quá tải (>100%)</div>
            <div class="legend-item"><div class="color-box bg-yellow"></div>Sắp đầy (>50%)</div>
            <div class="legend-item"><div class="color-box bg-green"></div>Còn trống</div>
            <div class="legend-item"><div class="color-box bg-gray"></div>Không có hàng</div>
        `;

        // 4. Sidebar
        const sidebarDiv = document.createElement("div");
        sidebarDiv.classList.add("location-sidebar");
        sidebarDiv.innerHTML = `
            <div class="sidebar-header">
                <h6>Cấu hình Sàn (m)</h6>
                <div class="floor-config">
                    <input type="number" id="floor_w_cfg" value="500"> <span>x</span>
                    <input type="number" id="floor_d_cfg" value="500">
                    <button id="btn_update_floor">Vẽ</button>
                </div>
            </div>
            <div class="sidebar-header" style="border:none; padding-bottom:0; margin-bottom:5px;">
                <h6>Chưa Setup</h6>
            </div>
        `;
        const sidebarList = document.createElement("div");
        sidebarList.classList.add("sidebar-content");
        sidebarDiv.appendChild(sidebarList);

        // 5. Selection Panel
        const panelDiv = document.createElement("div");
        panelDiv.classList.add("selection-panel");
        panelDiv.style.width = "350px"; 
        panelDiv.innerHTML = `
            <h5>
                <span id="panel_loc_name">Tên Vị Trí</span>
                <button class="btn-close-panel" id="btn_close_panel">&times;</button>
            </h5>
            
            <div class="panel-section">
                <h6>Căn chỉnh vị trí</h6>
                <div style="display:flex; gap:5px; margin-bottom:8px;">
                    <select id="anchor_select" style="width:100%; border:1px solid #ced4da; padding:2px; font-size:11px; border-radius:3px;">
                        <option value="">-- Chọn mốc --</option>
                    </select>
                </div>
                <div class="control-grid">
                    <button class="btn-align" data-dir="left"><i class="fa fa-arrow-left"></i> Trái</button>
                    <button class="btn-align" data-dir="top"><i class="fa fa-arrow-up"></i> Trên</button>
                    <button class="btn-align" data-dir="right"><i class="fa fa-arrow-right"></i> Phải</button>
                    <button class="btn-align" data-dir="front"><i class="fa fa-arrow-down"></i> Trước</button>
                    <button class="btn-align" data-dir="bottom"><i class="fa fa-arrow-down"></i> Dưới</button>
                    <button class="btn-align" data-dir="back"><i class="fa fa-arrow-up"></i> Sau</button>
                </div>
            </div>

            <div class="panel-section">
                <h6>Thông số (Mét & Pixel)</h6>
                <div id="parent_info_div" style="font-size:11px; color:#666; margin-bottom:5px; display:none;">
                    Thuộc Kệ: <b id="lbl_parent_name" style="color:#333;"></b>
                </div>

                <div class="input-row">
                   <div class="input-group"><label>D</label><input type="number" id="inp_l" step="0.1"></div>
                   <div class="input-group"><label>R</label><input type="number" id="inp_w" step="0.1"></div>
                   <div class="input-group"><label>C</label><input type="number" id="inp_h" step="0.1"></div>
                   <div class="input-group"><label>Cap</label><input type="number" id="inp_cap"></div>
                </div>
                <div class="input-row">
                   <div class="input-group"><label>X</label><input type="number" id="inp_pos_x" step="1"></div>
                   <div class="input-group"><label>Y</label><input type="number" id="inp_pos_y" step="1"></div>
                   <div class="input-group"><label>Z</label><input type="number" id="inp_pos_z" step="1"></div>
                </div>
            </div>
            
            <button class="btn-save" id="btn_save_changes">Lưu Cài Đặt</button>

            <div class="panel-section" style="padding:0; overflow:hidden;">
                <h6 style="padding:10px 10px 0;">Sản phẩm & Hoạt động</h6>
                <div class="list-container">
                    <div id="product_table_container">
                        <table>
                            <thead><tr><th>SP</th><th style="text-align:right;">SL</th></tr></thead>
                            <tbody id="product_list_body"></tbody>
                        </table>
                    </div>
                    <div id="product_empty_msg" class="empty-msg">(Trống)</div>
                </div>
                <div class="list-container" style="border-top:1px dashed #eee;">
                    <div id="picking_list_container"></div>
                    <div id="picking_empty_msg" class="empty-msg">(Không có phiếu)</div>
                </div>
            </div>
        `;

        start();

        async function start() {
            await rpc('/3Dstock/data', { 
                'company_id': user.context.allowed_company_ids[0], 
                'wh_id': wh_id 
            }).then(res => { data = res; });

            sidebarList.innerHTML = "";

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xf4f6f9);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 50000); 
            camera.position.set(0, 800, 1200); 

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(window.innerWidth, window.innerHeight / 1.164);
            renderer.setPixelRatio(window.devicePixelRatio);

            const content = $(self.rootRef.el).find('.o_content');
            $(self.rootRef.el).find('.o_list_renderer').addClass('d-none');
            $(self.rootRef.el).find('canvas').remove();
            
            content.append(renderer.domElement);
            content.append(whSelectorDiv);
            content.append(legendDiv);
            content.append(searchDiv);
            content.append(sidebarDiv);
            content.append(panelDiv);

            // Events Listeners UI
            document.querySelector(".customselect")?.addEventListener("change", warehouseChange);
            document.querySelector("#btn_close_panel").addEventListener("click", deselectObject);
            document.querySelector("#btn_update_floor").addEventListener("click", updateFloorSize);
            
            // Search
            const btnSearchLoc = document.getElementById("btn_search_loc");
            const inpSearchLoc = document.getElementById("loc_search_inp");
            btnSearchLoc.onclick = () => searchLocation(inpSearchLoc.value);
            inpSearchLoc.onkeyup = (e) => { if (e.key === 'Enter') searchLocation(inpSearchLoc.value); };

            const btnSearchProd = document.getElementById("btn_search_prod");
            const inpSearchProd = document.getElementById("product_search_inp");
            btnSearchProd.onclick = () => searchProduct(inpSearchProd.value);
            inpSearchProd.onkeyup = (e) => { if (e.key === 'Enter') searchProduct(inpSearchProd.value); };

            // Anchor
            document.getElementById("anchor_select").onchange = (e) => {
                const anchorCode = e.target.value;
                if (!anchorCode) { anchorObject = null; return; }
                const id = e.target.selectedOptions[0].getAttribute('data-id');
                if (meshMap[id]) anchorObject = meshMap[id];
            };

            // Align
            document.querySelectorAll(".btn-align").forEach(btn => {
                btn.onclick = async () => {
                    if (!selectedObject || !anchorObject) { alert("Chọn Gốc & Đối tượng!"); return; }
                    if (selectedObject === anchorObject) return;
                    alignObject(selectedObject, anchorObject, btn.dataset.dir);
                    
                    if (selectedObject.parent && selectedObject.parent.type === "Mesh") {
                        constrainMovement(selectedObject, selectedObject.parent);
                    }
                    await saveLocationPosition(selectedObject);
                    transformControl.attach(selectedObject);
                };
            });

            // --- SAVE LOGIC (SỬA LỖI MẤT VỊ TRÍ CON) ---
            document.getElementById("btn_save_changes").onclick = async () => {
                if (!selectedObject) return;
                const locId = selectedObject.userData.loc_id;
                
                const l = parseFloat(document.getElementById('inp_l').value) || 0;
                const w = parseFloat(document.getElementById('inp_w').value) || 0;
                const h = parseFloat(document.getElementById('inp_h').value) || 0;
                const cap = parseInt(document.getElementById('inp_cap').value) || 0;
                
                const px = parseFloat(document.getElementById('inp_pos_x').value) || 0;
                const py = parseFloat(document.getElementById('inp_pos_y').value) || 0;
                const pz = parseFloat(document.getElementById('inp_pos_z').value) || 0;
                
                const payload = {
                    'length': l, 'width': w, 'height': h, 'max_capacity': cap,
                    'pos_x': px, 'pos_y': py, 'pos_z': pz
                };

                // 1. Lưu DB
                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location', method: 'write',
                    args: [[locId], payload], kwargs: {},
                });
                
                // 2. Cập nhật Visual
                const worldVec = new THREE.Vector3(px, py, pz);
                
                // Nếu vật thể là CON
                if (selectedObject.parent && selectedObject.parent.type === "Mesh") {
                    // Update matrix cha trước để đảm bảo tính toán đúng
                    selectedObject.parent.updateMatrixWorld(true);
                    // Chuyển đổi tọa độ thế giới (Input) -> Tọa độ cục bộ (Local)
                    const localVec = selectedObject.parent.worldToLocal(worldVec.clone());
                    selectedObject.position.copy(localVec);
                    
                    constrainMovement(selectedObject, selectedObject.parent); 
                } else {
                    // Nếu là vật thể độc lập
                    selectedObject.position.set(px, py, pz);
                }

                updateMeshDimensions(selectedObject, l, w, h);
                selectedObject.updateMatrixWorld(true);
                transformControl.attach(selectedObject);

                // 3. Update Con (Nếu là Cha)
                if (selectedObject.children.length > 0) {
                    selectedObject.children.forEach(child => {
                        if (child.type === "Mesh" && child.userData.loc_id) {
                            child.updateMatrixWorld(true);
                            saveLocationPosition(child);
                        }
                    });
                }
                
                alert("Đã lưu thành công!");
            };

            controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true; controls.dampingFactor = 0.1;

            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            
            // Xử lý kéo thả (Có Constraint + Chống âm đất)
            transformControl.addEventListener('change', function(event) {
                if (transformControl.dragging && transformControl.object) {
                    const obj = transformControl.object;
                    
                    // 1. Ràng buộc Cha/Con
                    if (obj.parent && obj.parent.type === "Mesh") {
                        constrainMovement(obj, obj.parent);
                    } else {
                        // 2. CHỐNG ÂM ĐẤT (Nếu ở ngoài)
                        // Đảm bảo đáy vật thể (y - h/2) >= 0 => y >= h/2
                        // Lưu ý: Geometry đã translate(0, h/2, 0), nên tâm hình học là ở đáy.
                        // Tuy nhiên transformControl điều khiển vị trí của Mesh (gốc tọa độ Mesh).
                        // Gốc Mesh ở đáy (do ta translate geometry) -> Y >= 0.
                        // Nhưng nếu ta chưa translate geometry (pivot ở giữa) -> Y >= H/2.
                        
                        // Ở hàm create3DBox, ta dùng geo.translate(0, h/2, 0). Nghĩa là:
                        // Tọa độ (0,0,0) của Mesh chính là đáy của hộp.
                        // Vậy chỉ cần obj.position.y >= 0 là được.
                        if (obj.position.y < 0) obj.position.y = 0;
                    }

                    // Update Input
                    const worldPos = new THREE.Vector3();
                    obj.getWorldPosition(worldPos);
                    document.getElementById('inp_pos_x').value = Math.round(worldPos.x);
                    document.getElementById('inp_pos_y').value = Math.round(worldPos.y);
                    document.getElementById('inp_pos_z').value = Math.round(worldPos.z);
                }
            });

            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value;
                if (!event.value && transformControl.object) {
                    saveLocationPosition(transformControl.object);
                    const obj = transformControl.object;
                    if (obj.children.length > 0) {
                        obj.children.forEach(child => {
                            if (child.type === "Mesh" && child.userData.loc_id) {
                                saveLocationPosition(child);
                            }
                        });
                    }
                }
            });
            scene.add(transformControl);

            window.addEventListener('keydown', (e) => {
                if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'SELECT') return;
                const moveSpeed = 30; 
                const forward = new THREE.Vector3();
                camera.getWorldDirection(forward); forward.y = 0; forward.normalize();
                const right = new THREE.Vector3();
                right.crossVectors(forward, camera.up).normalize();

                switch(e.key.toLowerCase()) {
                    case 'w': case 'arrowup': camera.position.addScaledVector(forward, moveSpeed); controls.target.addScaledVector(forward, moveSpeed); break;
                    case 's': case 'arrowdown': camera.position.addScaledVector(forward, -moveSpeed); controls.target.addScaledVector(forward, -moveSpeed); break;
                    case 'a': case 'arrowleft': camera.position.addScaledVector(right, -moveSpeed); controls.target.addScaledVector(right, -moveSpeed); break;
                    case 'd': case 'arrowright': camera.position.addScaledVector(right, moveSpeed); controls.target.addScaledVector(right, moveSpeed); break;
                }
                controls.update(); 
            });

            createFloor(floorWidth, floorDepth);

            // --- INIT OBJECTS ---
            group = new THREE.Group();
            meshMap = {};

            const anchorSel = document.getElementById("anchor_select");
            anchorSel.innerHTML = '<option value="">-- Chọn mốc --</option>';
            const locDatalist = document.getElementById("loc_datalist");
            locDatalist.innerHTML = "";

            for (let [key, value] of Object.entries(data)) {
                const hasPos = (value[0] !== 0 || value[1] !== 0 || value[2] !== 0);
                
                let optList = document.createElement("option"); optList.value = key; locDatalist.appendChild(optList);

                if (hasPos) {
                    const mesh = await create3DBox(key, value);
                    meshMap[value[6]] = mesh; 
                    group.add(mesh); 
                    
                    let opt1 = document.createElement("option"); 
                    opt1.value = key; opt1.text = key; 
                    opt1.setAttribute('data-id', value[6]); 
                    anchorSel.appendChild(opt1);
                } else {
                    createSidebarItem(key, value);
                }
            }
            scene.add(group);

            // Attach Parent/Child
            for (let id in meshMap) {
                const mesh = meshMap[id];
                const pid = mesh.userData.parent_id;
                if (pid && meshMap[pid]) {
                    updateParentVisual(meshMap[pid]);
                    meshMap[pid].attach(mesh);
                }
            }
            
            raycaster = new THREE.Raycaster();
            animate();

            const canvas = renderer.domElement;
            canvas.addEventListener("dragover", (e) => e.preventDefault());
            canvas.addEventListener("drop", onDropLocation);
            canvas.addEventListener('click', onCanvasClick);
        }

        // --- CORE FUNCTIONS ---
        function searchLocation(name) {
            if(!name) return;
            let found = null;
            scene.traverse(obj => {
                if(obj.type === 'Mesh' && obj.name === name && obj.userData.loc_id) {
                    found = obj;
                }
            });
            if (found) {
                selectObject(found);
                const worldPos = new THREE.Vector3();
                found.getWorldPosition(worldPos);
                controls.target.copy(worldPos);
                camera.position.set(worldPos.x + 200, worldPos.y + 200, worldPos.z + 200);
                controls.update();
            } else {
                alert("Không tìm thấy: " + name);
            }
        }

        function constrainMovement(child, parent) {
            const pGeo = parent.geometry.parameters;
            const cGeo = child.geometry.parameters;
            const minX = -(pGeo.width / 2) + (cGeo.width / 2);
            const maxX = (pGeo.width / 2) - (cGeo.width / 2);
            const minZ = -(pGeo.depth / 2) + (cGeo.depth / 2);
            const maxZ = (pGeo.depth / 2) - (cGeo.depth / 2);
            // Y: Con phải nằm trên đáy cha.
            const minY = 0; 
            const maxY = pGeo.height - cGeo.height;

            if (minX <= maxX) child.position.x = Math.max(minX, Math.min(maxX, child.position.x)); else child.position.x = 0;
            if (minZ <= maxZ) child.position.z = Math.max(minZ, Math.min(maxZ, child.position.z)); else child.position.z = 0;
            if (minY <= maxY) child.position.y = Math.max(minY, Math.min(maxY, child.position.y)); else child.position.y = 0;
        }

        function alignObject(target, anchor, direction) {
            const boxT = new THREE.Box3().setFromObject(target);
            const boxA = new THREE.Box3().setFromObject(anchor);
            const sizeT = new THREE.Vector3(); boxT.getSize(sizeT);
            const sizeA = new THREE.Vector3(); boxA.getSize(sizeA);
            const centerA = new THREE.Vector3(); boxA.getCenter(centerA);
            const newPos = centerA.clone();
            const margin = 2; 
            switch(direction) {
                case 'right': newPos.x = centerA.x + (sizeA.x/2) + (sizeT.x/2) + margin; newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2); newPos.z = centerA.z; break;
                case 'left': newPos.x = centerA.x - (sizeA.x/2) - (sizeT.x/2) - margin; newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2); newPos.z = centerA.z; break;
                case 'top': newPos.y = centerA.y + (sizeA.y/2) + (sizeT.y/2); newPos.x = centerA.x; newPos.z = centerA.z; break;
                case 'bottom': newPos.y = centerA.y - (sizeA.y/2) - (sizeT.y/2); newPos.x = centerA.x; newPos.z = centerA.z; break;
                case 'front': newPos.z = centerA.z + (sizeA.z/2) + (sizeT.z/2) + margin; newPos.x = centerA.x; newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2); break;
                case 'back': newPos.z = centerA.z - (sizeA.z/2) - (sizeT.z/2) - margin; newPos.x = centerA.x; newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2); break;
            }
            if (target.parent && target.parent.type === 'Mesh') {
                target.parent.worldToLocal(newPos);
            }
            target.position.copy(newPos);
        }

        async function create3DBox(key, value) {
            const l = value[3] > 0 ? value[3] : 50;
            const w = value[4] > 0 ? value[4] : 50;
            const h = value[5] > 0 ? value[5] : 50;
            
            const geo = new THREE.BoxGeometry(l, h, w);
            geo.translate(0, h/2, 0); 
            
            let col = 0x8c8c8c; let op = 0.5;
            await rpc('/3Dstock/data/quantity', { 'loc_code': key }).then(q => {
                if (q[0] > 0) { 
                   if (q[1] > 100) { col = 0xcc0000; op = 0.8; }
                   else if (q[1] > 50) { col = 0xe6b800; op = 0.8; }
                   else if (q[1] > 0) { col = 0x00802b; op = 0.8; } 
                   else { col = 0x8c8c8c; op = 0.5; }
                } else { 
                   if(q[1] == -1) { col = 0x00802b; op = 0.8; } 
                   else { col = 0x8c8c8c; op = 0.5; }
                }
            });

            const mat = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: op });
            const mesh = new THREE.Mesh(geo, mat);
            const edges = new THREE.EdgesGeometry(geo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            mesh.add(line);
            
            mesh.position.set(value[0], value[1], value[2]);
            mesh.name = key;
            mesh.userData = { color: col, loc_id: value[6], parent_id: value[7] };
            
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000 }); // Text màu đen
                
                // Kích thước text dựa trên cạnh nhỏ nhất để không bị tràn
                let baseSize = Math.min(l, w, h) / 2.0; 
                
                const shapes = font.generateShapes(key, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                
                // Canh giữa text
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                const yMid = - 0.5 * ( tGeo.boundingBox.max.y - tGeo.boundingBox.min.y );
                tGeo.translate( xMid, yMid, 0 );
                
                // Scale text nếu quá dài
                const tW = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                // Xác định cạnh sẽ chứa text (nếu w > l thì text nằm trên cạnh w)
                let containerW = (w > l) ? w : l;
                if (tW > containerW * 0.9) { 
                    const s = (containerW * 0.9) / tW; 
                    tGeo.scale(s,s,1); 
                }

                const textMesh = new THREE.Mesh(tGeo, textMat);
                
                // --- ĐỊNH VỊ TEXT Ở MẶT TRƯỚC ---
                textMesh.position.y = h / 2; // Nằm giữa chiều cao
                
                if (w > l) {
                    // Nếu vật thể dài theo trục Z (Rộng > Dài), đặt text ở mặt bên (trục X)
                    // Xoay 90 độ quanh trục Y để text hướng ra ngoài
                    textMesh.rotation.y = Math.PI / 2;
                    textMesh.position.x = l / 2 + 1; // Đẩy ra khỏi mặt bên 1 chút
                    textMesh.position.z = 0;
                } else {
                    // Nếu vật thể dài theo trục X (Dài > Rộng), đặt text ở mặt trước (trục Z)
                    textMesh.rotation.y = 0;
                    textMesh.position.z = w / 2 + 1; // Đẩy ra khỏi mặt trước 1 chút
                    textMesh.position.x = 0;
                }

                mesh.add(textMesh);
            });
            return mesh;
        }
        function updateParentVisual(mesh) {
            mesh.material.wireframe = true;
            mesh.material.color.set(0x000000);
            mesh.material.opacity = 0.1;
            mesh.userData.is_parent = true;
        }

        async function onCanvasClick(event) {
            if (transformControl.dragging) return;
            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            raycaster.setFromCamera(pointer, camera);
            const intersects = raycaster.intersectObjects(group.children, true); 

            if (intersects.length > 0) {
                const hits = intersects.filter(i => i.object.type === 'Mesh' && i.object.userData.loc_id);
                let finalTarget = hits.find(h => !h.object.userData.is_parent);
                if (!finalTarget && hits.length > 0) finalTarget = hits[0];
                if (finalTarget) selectObject(finalTarget.object);
            } else {
                const gGizmo = raycaster.intersectObjects(transformControl.children, true);
                if (gGizmo.length === 0) deselectObject();
            }
        }

        async function selectObject(mesh) {
            if (selectedObject === mesh) return;
            selectedObject = mesh;
            transformControl.attach(mesh);
            panelDiv.style.display = "block";
            
            document.getElementById("panel_loc_name").innerText = mesh.name;
            const worldPos = new THREE.Vector3();
            mesh.getWorldPosition(worldPos);
            document.getElementById('inp_pos_x').value = Math.round(worldPos.x);
            document.getElementById('inp_pos_y').value = Math.round(worldPos.y);
            document.getElementById('inp_pos_z').value = Math.round(worldPos.z);

            const locId = mesh.userData.loc_id;
            const res = await rpc('/web/dataset/call_kw', {
                model: 'stock.location', method: 'read',
                args: [[locId], ['length', 'width', 'height', 'max_capacity', 'location_id']], kwargs: {}
            });
            if (res && res.length > 0) {
                const info = res[0];
                document.getElementById('inp_l').value = info.length;
                document.getElementById('inp_w').value = info.width;
                document.getElementById('inp_h').value = info.height;
                document.getElementById('inp_cap').value = info.max_capacity;
                
                const pInfo = document.getElementById("parent_info_div");
                if (pInfo) {
                    if(info.location_id) {
                        pInfo.style.display = "block";
                        const lblParent = document.getElementById("lbl_parent_name");
                        if(lblParent) lblParent.innerText = info.location_id[1];
                    } else {
                        pInfo.style.display = "none";
                    }
                }
            }

            const tbody = document.getElementById('product_list_body');
            const pEmpty = document.getElementById('product_empty_msg');
            tbody.innerHTML = "";
            pEmpty.style.display = "block"; pEmpty.innerText = "Đang tải...";
            
            await rpc('/3Dstock/data/product', { 'loc_code': mesh.name }).then(prodData => {
                tbody.innerHTML = "";
                const list = prodData.product_list || [];
                if (list.length === 0) {
                    pEmpty.style.display = "block"; pEmpty.innerText = "(Trống)";
                } else {
                    pEmpty.style.display = "none";
                    list.forEach(p => {
                        const tr = document.createElement("tr");
                        tr.innerHTML = `<td>${p[0]}</td><td style="text-align:right;">${p[1]}</td>`;
                        tbody.appendChild(tr);
                    });
                }
            });

            const pickDiv = document.getElementById("picking_list_container");
            const pkEmpty = document.getElementById("picking_empty_msg");
            pickDiv.innerHTML = "";
            pkEmpty.style.display = "block"; pkEmpty.innerText = "Đang tải...";
            
            await rpc('/3Dstock/data/pickings', { 'loc_code': mesh.name }).then(picks => {
                pickDiv.innerHTML = "";
                if (picks.length === 0) {
                    pkEmpty.style.display = "block"; pkEmpty.innerText = "(Không có phiếu)";
                } else {
                    pkEmpty.style.display = "none";
                    picks.forEach(p => {
                        let cl = p.type==="Nhập hàng"?"#28a745":p.type==="Xuất hàng"?"#dc3545":"#ffc107";
                        const div = document.createElement("div");
                        div.style.borderBottom = "1px solid #f1f3f5"; div.style.padding = "4px 0";
                        div.innerHTML = `<div style="font-weight:600; display:flex; justify-content:space-between; font-size:11px;"><span>${p.name}</span><span style="color:${cl};">${p.type}</span></div><div style="font-size:10px; color:#999;">${p.origin||''} - ${p.state}</div>`;
                        pickDiv.appendChild(div);
                    });
                }
            });
        }

        function deselectObject() {
            selectedObject = null;
            transformControl.detach();
            panelDiv.style.display = "none";
        }

        function createSidebarItem(code, val) {
            const item = document.createElement("div");
            item.classList.add("location-item"); item.innerText = code; item.draggable = true;
            item.addEventListener("dragstart", (e) => {
                const dragData = JSON.stringify({
                    id: val[6], code: code,
                    l: val[3]>0?val[3]:50, w: val[4]>0?val[4]:50, h: val[5]>0?val[5]:50
                });
                e.dataTransfer.setData("text/plain", dragData);
            });
            sidebarList.appendChild(item);
        }

        async function onDropLocation(e) {
            e.preventDefault();
            const raw = e.dataTransfer.getData("text/plain"); if (!raw) return;
            const item = JSON.parse(raw);
            const mouse = new THREE.Vector2();
            mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
            mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObject(dragPlane);
            if (intersects.length > 0) {
                const p = intersects[0].point;
                const mesh = await create3DBox(item.code, [p.x, 0, p.z, item.l, item.w, item.h, item.id, false]);
                meshMap[item.id] = mesh; group.add(mesh);
                
                let opt1 = document.createElement("option"); 
                opt1.value = item.code; opt1.text = item.code; 
                opt1.setAttribute('data-id', item.id); 
                document.getElementById("anchor_select").appendChild(opt1);
                
                let opt2 = document.createElement("option"); 
                opt2.value = item.code; 
                document.getElementById("loc_datalist").appendChild(opt2);

                Array.from(sidebarList.children).forEach(child => { if (child.innerText === item.code) sidebarList.removeChild(child); });
                await saveLocationPosition(mesh);
                selectObject(mesh);
            }
        }

        async function saveLocationPosition(obj) {
            if (!obj.userData.loc_id) return;
            const worldPos = new THREE.Vector3();
            obj.getWorldPosition(worldPos);
            await rpc('/web/dataset/call_kw', {
                model: 'stock.location', method: 'write',
                args: [[obj.userData.loc_id], { 'pos_x': worldPos.x, 'pos_y': worldPos.y, 'pos_z': worldPos.z }], kwargs: {}
            });
        }

        function updateMeshDimensions(mesh, l, w, h) {
            const pxL = l * 3.779 * 2; const pxW = w * 3.779 * 2; const pxH = h * 3.779 * 2;
            const geo = new THREE.BoxGeometry(pxL, pxH, pxW); geo.translate(0, pxH/2, 0);
            mesh.geometry.dispose(); mesh.geometry = geo;
            
            const line = mesh.children.find(c => c.type === 'LineSegments');
            if(line) { line.geometry.dispose(); line.geometry = new THREE.EdgesGeometry(geo); }
            
            // Xóa text cũ
            const oldText = mesh.children.find(c => c.type === 'Mesh' && c !== line && !c.userData.loc_id); 
            if (oldText) mesh.remove(oldText);
            
            // Tạo text mới (Logic giống hệt create3DBox)
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000 });
                let baseSize = Math.min(pxL, pxW, pxH) / 2.0;
                const shapes = font.generateShapes(mesh.name, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                const yMid = - 0.5 * ( tGeo.boundingBox.max.y - tGeo.boundingBox.min.y );
                tGeo.translate( xMid, yMid, 0 );
                
                const tW = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                let containerW = (pxW > pxL) ? pxW : pxL;
                if (tW > containerW * 0.9) { const s = (containerW * 0.9)/tW; tGeo.scale(s,s,1); }

                const textMesh = new THREE.Mesh(tGeo, textMat);
                textMesh.position.y = pxH / 2; 
                
                if (pxW > pxL) {
                    textMesh.rotation.y = Math.PI / 2;
                    textMesh.position.x = pxL / 2 + 1;
                    textMesh.position.z = 0;
                } else {
                    textMesh.rotation.y = 0;
                    textMesh.position.z = pxW / 2 + 1;
                    textMesh.position.x = 0;
                }
                
                mesh.add(textMesh);
            });
        }
        function warehouseChange() {
            wh_id = document.querySelector(".customselect").value; start();
        }

        function createFloor(w, d) {
            const visualW = w * 3.779 * 2; const visualD = d * 3.779 * 2;
            if (baseMesh) scene.remove(baseMesh); if (dragPlane) scene.remove(dragPlane);
            if (window.gridHelper) scene.remove(window.gridHelper);

            // Plane (Ground) - Màu trắng sáng hơn
            const geo = new THREE.PlaneGeometry(visualW, visualD);
            const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, depthWrite: false });
            baseMesh = new THREE.Mesh(geo, mat); baseMesh.rotation.x = -Math.PI / 2; baseMesh.position.y = -0.5; scene.add(baseMesh);
            
            // Grid Helper (Lưới đậm hơn 1 chút để rõ)
            const grid = new THREE.GridHelper(Math.max(visualW, visualD), 20, 0xaaaaaa, 0xdddddd);
            grid.position.y = 0;
            scene.add(grid);
            window.gridHelper = grid;

            const pGeo = new THREE.PlaneGeometry(50000, 50000); 
            dragPlane = new THREE.Mesh(pGeo, new THREE.MeshBasicMaterial({visible:false})); 
            dragPlane.rotation.x = -Math.PI / 2; scene.add(dragPlane);
        }

        function updateFloorSize() {
            const w = parseFloat(document.getElementById('floor_w_cfg').value) || 500;
            const d = parseFloat(document.getElementById('floor_d_cfg').value) || 500;
            createFloor(w, d);
        }

        async function searchProduct(keyword) {
            if (!keyword) {
                scene.traverse(obj => {
                    if (obj.userData.loc_id) {
                       obj.material.color.set(obj.userData.color);
                       obj.material.opacity = obj.userData.is_parent ? 0.2 : (obj.userData.color===0x8c8c8c?0.5:0.8);
                    }
                });
                return;
            }
            const locCodes = await rpc('/3Dstock/search_product', { keyword: keyword, wh_id: wh_id });
            if (locCodes.length === 0) { alert("Không thấy!"); return; }
            let first = null;
            scene.traverse(obj => {
                if (obj.userData.loc_id) {
                    if (locCodes.includes(obj.name)) {
                        obj.material.color.set(0xff00ff); obj.material.opacity = 1;
                        if (!first) first = obj;
                    } else {
                        obj.material.color.set(0xeeeeee); obj.material.opacity = 0.1;
                    }
                }
            });
            if(first) { controls.target.copy(first.position); controls.update(); }
        }

        function animate() {
            requestAnimationFrame(animate); renderer.render(scene, camera); controls.update();
        }
    }
}

registry.category("views").add("3d_button_in_stock", {
    ...listView,
    Controller: Stock3DController,
    buttonTemplate: 'stock_3d_custom_view.ListView.Buttons'
});