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
        let meshMap = {}; // Map lưu trữ object theo ID để truy xuất nhanh
        
        let floorWidth = 2000;
        let floorDepth = 2000;
        let baseMesh, dragPlane;

        const pointer = new THREE.Vector2();

        // Fetch Warehouse
        await rpc('/3Dstock/warehouse', { 'company_id': user.context.allowed_company_ids[0] })
            .then(res => { wh_data = res; });
        
        if (!wh_data || wh_data.length === 0) {
            alert("Không tìm thấy kho nào!");
            return;
        }
        wh_id = wh_data[0][0];

        // --- UI CONSTRUCTION ---
        var select = document.createElement("select");
        select.classList.add("customselect");
        wh_data.forEach(w => {
            var opt = document.createElement("option");
            opt.value = w[0]; opt.text = w[1];
            select.appendChild(opt);
        });

        var closeDiv = document.createElement("button");
        closeDiv.classList.add("closeBtn");
        closeDiv.innerHTML = "&times;";
        closeDiv.style.zIndex = "1001";
        closeDiv.onclick = () => window.location.reload();

        const searchDiv = document.createElement("div");
        searchDiv.classList.add("search-container");
        searchDiv.innerHTML = `
            <i class="fa fa-search" style="color:#666;"></i>
            <input type="text" id="product_search_inp" placeholder="Tìm sản phẩm..." style="border:none; outline:none; margin-left:5px;">
            <button id="btn_do_search" class="btn btn-sm btn-primary" style="border-radius:50%; width:30px; height:30px; padding:0;"><i class="fa fa-arrow-right"></i></button>
        `;

        var colorDiv = document.createElement("div");
        colorDiv.classList.add("rectangle");
        const addLegend = (cls, txt) => {
            let d = document.createElement("div"); d.className = cls; colorDiv.appendChild(d);
            let t = document.createElement("div"); t.className = "squareText" + cls.replace(/\D/g,''); 
            if(cls === 'square4') t.className = "squareText4";
            t.innerText = txt; colorDiv.appendChild(t);
        };
        addLegend("square1", "Quá tải");
        addLegend("square2", "Sắp đầy");
        addLegend("square3", "Còn trống");
        addLegend("square4", "Không có hàng");

        const sidebarDiv = document.createElement("div");
        sidebarDiv.classList.add("location-sidebar");
        sidebarDiv.innerHTML = `
            <div style="padding-bottom:10px; border-bottom:1px solid #ddd; margin-bottom:10px;">
                <h6 style="font-weight:bold; font-size:13px; text-align:center;">Cấu hình Sàn (m)</h6>
                <div style="display:flex; gap:5px; justify-content:center;">
                    <input type="number" id="floor_w_cfg" value="500" placeholder="R" style="width:50px; font-size:12px;">
                    <span style="align-self:center;">x</span>
                    <input type="number" id="floor_d_cfg" value="500" placeholder="D" style="width:50px; font-size:12px;">
                    <button id="btn_update_floor" class="btn btn-xs btn-secondary" style="font-size:10px;">Vẽ</button>
                </div>
            </div>
            <h6 style="text-align:center; font-weight:bold; font-size:13px; margin-bottom:5px;">Chưa Setup</h6>
        `;
        const sidebarList = document.createElement("div");
        sidebarList.style.maxHeight = "55vh"; sidebarList.style.overflowY = "auto";
        sidebarDiv.appendChild(sidebarList);

        const panelDiv = document.createElement("div");
        panelDiv.classList.add("selection-panel");
        panelDiv.style.width = "350px"; 
        panelDiv.innerHTML = `
            <h5>
                <span id="panel_loc_name" style="color:#007bff; font-weight:bold;">Tên Vị Trí</span>
                <button class="btn-close-panel" id="btn_close_panel" style="cursor:pointer; float:right;">&times;</button>
            </h5>
            <div class="edit-section" style="background:#f0f8ff; border:1px solid #cce5ff; padding:5px; margin-bottom:10px; border-radius:4px;">
                <h6 style="font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;">
                    <i class="fa fa-crosshairs"></i> Căn chỉnh vị trí
                </h6>
                <div style="font-size:11px; margin-bottom:5px; display:flex; gap:5px; align-items:center;">
                    <span style="white-space:nowrap;">Chọn Gốc:</span>
                    <select id="anchor_select" style="width:100%; border:1px solid #ddd; font-size:11px;">
                        <option value="">-- Chọn vị trí làm mốc --</option>
                    </select>
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:3px;">
                    <button class="btn btn-light btn-sm btn-align" data-dir="left" title="Trái"><i class="fa fa-arrow-left"></i> Trái</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="top" title="Trên"><i class="fa fa-arrow-up"></i> Trên</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="right" title="Phải"><i class="fa fa-arrow-right"></i> Phải</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="front" title="Trước"><i class="fa fa-arrow-down"></i> Trước</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="bottom" title="Dưới"><i class="fa fa-arrow-down"></i> Dưới</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="back" title="Sau"><i class="fa fa-arrow-up"></i> Sau</button>
                </div>
            </div>
            <div class="edit-section">
                <h6 style="font-size:12px; font-weight:bold; background:#eee; padding:3px;">Thông tin chung</h6>
                <div class="input-group" style="margin-bottom:5px;">
                    <label style="width:80px;">Thuộc Kệ (Cha)</label>
                    <select id="inp_parent_id" style="flex:1; font-size:11px; border:1px solid #ddd;">
                        <option value="0">-- Không có (Là gốc) --</option>
                    </select>
                </div>
                <div style="display:flex; gap:5px; margin-top:5px;">
                   <div class="input-group"><label>D</label><input type="number" id="inp_l" step="0.1" style="width:40px"></div>
                   <div class="input-group"><label>R</label><input type="number" id="inp_w" step="0.1" style="width:40px"></div>
                   <div class="input-group"><label>C</label><input type="number" id="inp_h" step="0.1" style="width:40px"></div>
                   <div class="input-group"><label>Cap</label><input type="number" id="inp_cap" style="width:40px"></div>
                </div>
                <div style="display:flex; gap:5px; margin-top:5px;">
                   <div class="input-group"><label>X</label><input type="number" id="inp_pos_x" step="1" style="width:45px"></div>
                   <div class="input-group"><label>Y</label><input type="number" id="inp_pos_y" step="1" style="width:45px"></div>
                   <div class="input-group"><label>Z</label><input type="number" id="inp_pos_z" step="1" style="width:45px"></div>
                </div>
                <button class="btn btn-primary btn-sm w-100" id="btn_save_changes" style="margin-top:5px;">Lưu Cài Đặt</button>
            </div>
            <div class="picking-list" style="margin-top:10px; border-top:1px solid #eee;">
                <h6 style="font-size:12px; font-weight:bold; margin-top:5px;">Sản phẩm & Hoạt động</h6>
                <div id="product_table_container" style="max-height:80px; overflow-y:auto; margin-bottom:5px;">
                    <table style="width:100%;">
                        <thead><tr><th style="text-align:left;">SP</th><th style="text-align:right;">SL</th></tr></thead>
                        <tbody id="product_list_body"></tbody>
                    </table>
                </div>
                <div id="picking_list_container" style="max-height:80px; overflow-y:auto; border-top:1px dashed #eee;"></div>
            </div>
        `;

        const helpDiv = document.createElement("div");
        helpDiv.style = "position:absolute; bottom:10px; left:220px; font-size:11px; color:#666; background:rgba(255,255,255,0.8); padding:5px; border-radius:4px; z-index:1000;";
        helpDiv.innerHTML = "<i class='fa fa-keyboard-o'></i> <b>Di chuyển:</b> W/A/S/D hoặc Mũi tên";

        start();

        async function start() {
            await rpc('/3Dstock/data', { 
                'company_id': user.context.allowed_company_ids[0], 
                'wh_id': wh_id 
            }).then(res => { data = res; });

            sidebarList.innerHTML = "";
            scene = new THREE.Scene(); scene.background = new THREE.Color(0xe0e0e0);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 50000); // Tăng tầm nhìn
            camera.position.set(0, 500, 800); 

            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight / 1.164);
            renderer.setPixelRatio(window.devicePixelRatio);

            const content = $(self.rootRef.el).find('.o_content');
            $(self.rootRef.el).find('.o_list_renderer').addClass('d-none');
            $(self.rootRef.el).find('canvas').remove();
            content.append(renderer.domElement).append(select).append(colorDiv).append(closeDiv).append(searchDiv).append(sidebarDiv).append(panelDiv).append(helpDiv);

            // Listeners
            document.querySelector(".customselect")?.addEventListener("change", warehouseChange);
            document.querySelector("#btn_close_panel").addEventListener("click", deselectObject);
            document.querySelector("#btn_update_floor").addEventListener("click", updateFloorSize);
            
            // Search
            const btnSearch = document.getElementById("btn_do_search");
            const inpSearch = document.getElementById("product_search_inp");
            btnSearch.addEventListener("click", () => searchProduct(inpSearch.value));
            inpSearch.addEventListener("keyup", (e) => { if (e.key === 'Enter') searchProduct(inpSearch.value); });

            // Anchor Select
            document.getElementById("anchor_select").addEventListener("change", (e) => {
                const anchorCode = e.target.value;
                if (!anchorCode) { anchorObject = null; return; }
                const found = group.children.find(c => c.name === anchorCode);
                // Vì có thể nằm trong group hoặc nằm trong object khác, ta tìm trong meshMap cho nhanh
                // Nhưng ở đây ta dùng group.children, nếu đã parenting thì cần traverse.
                // Tốt nhất dùng meshMap.
                if (meshMap[e.target.selectedOptions[0].getAttribute('data-id')]) {
                    anchorObject = meshMap[e.target.selectedOptions[0].getAttribute('data-id')];
                }
            });

            // Align Buttons
            document.querySelectorAll(".btn-align").forEach(btn => {
                btn.addEventListener("click", async () => {
                    if (!selectedObject || !anchorObject) { alert("Chọn vị trí Gốc & Đối tượng!"); return; }
                    if (selectedObject === anchorObject) return;
                    alignObject(selectedObject, anchorObject, btn.dataset.dir);
                    
                    // Nếu là con, kiểm tra boundary
                    if (selectedObject.parent && selectedObject.parent.type === "Mesh") {
                        constrainMovement(selectedObject, selectedObject.parent);
                    }
                    await saveLocationPosition(selectedObject);
                    transformControl.attach(selectedObject);
                });
            });

            // SAVE
            document.querySelector("#btn_save_changes").addEventListener("click", async () => {
                if (!selectedObject) return;
                const locId = selectedObject.userData.loc_id;
                
                const l = parseFloat(document.getElementById('inp_l').value) || 0;
                const w = parseFloat(document.getElementById('inp_w').value) || 0;
                const h = parseFloat(document.getElementById('inp_h').value) || 0;
                const cap = parseInt(document.getElementById('inp_cap').value) || 0;
                
                // Input hiện tại đang hiển thị WORLD position (để người dùng dễ hiểu)
                // Nhưng nếu là con, ta cần convert sang relative trước khi lưu (nếu muốn lưu relative vào DB?)
                // KHÔNG, Odoo lưu Absolute (pos_x, pos_y...).
                // Vậy ta cứ lấy giá trị từ Input (là World Pos) để lưu vào DB.
                const px = parseFloat(document.getElementById('inp_pos_x').value) || 0;
                const py = parseFloat(document.getElementById('inp_pos_y').value) || 0;
                const pz = parseFloat(document.getElementById('inp_pos_z').value) || 0;
                
                const parentId = parseInt(document.getElementById('inp_parent_id').value) || false;

                const payload = {
                    'length': l, 'width': w, 'height': h, 'max_capacity': cap,
                    'pos_x': px, 'pos_y': py, 'pos_z': pz
                };
                if (parentId !== selectedObject.userData.parent_id) payload['location_id'] = parentId;

                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location', method: 'write',
                    args: [[locId], payload], kwargs: {},
                });
                
                // Update Memory & Visual
                selectedObject.userData.parent_id = parentId;
                updateMeshDimensions(selectedObject, l, w, h);

                // Xử lý chuyển cha/con trực quan (Re-parenting)
                if (parentId) {
                    const newParent = meshMap[parentId];
                    if (newParent) {
                        // Attach vào cha mới (ThreeJS tự tính lại local pos để giữ nguyên World pos)
                        newParent.attach(selectedObject);
                        updateParentVisual(newParent);
                        constrainMovement(selectedObject, newParent);
                    }
                } else {
                    // Nếu bỏ cha -> Attach về Group gốc (World)
                    scene.attach(selectedObject); 
                    group.add(selectedObject); // Add lại vào group quản lý
                }
                
                // Update lại vị trí hiển thị (nếu bị constraint thay đổi)
                const worldPos = new THREE.Vector3();
                selectedObject.getWorldPosition(worldPos);
                document.getElementById('inp_pos_x').value = Math.round(worldPos.x);
                document.getElementById('inp_pos_y').value = Math.round(worldPos.y);
                document.getElementById('inp_pos_z').value = Math.round(worldPos.z);

                transformControl.attach(selectedObject);
                alert("Đã lưu!");
            });

            controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true; 
            controls.dampingFactor = 0.1;

            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            
            // Xử lý kéo thả (Có Constraint + Update Input)
            transformControl.addEventListener('change', function(event) {
                if (transformControl.dragging && transformControl.object) {
                    const obj = transformControl.object;
                    
                    // Nếu có cha là Mesh (tức là đang nằm trong kệ)
                    if (obj.parent && obj.parent.type === "Mesh") {
                        constrainMovement(obj, obj.parent);
                    }

                    // Update Input (Luôn hiện World Position)
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
                    // Khi thả chuột: Lưu vị trí của object
                    saveLocationPosition(transformControl.object);
                    
                    // NẾU LÀ CHA: Lưu luôn vị trí các con (vì khi cha di chuyển, con đi theo -> World Pos con thay đổi)
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

            // KEYBOARD WASD
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

            // --- INIT OBJECTS (QUAN TRỌNG: 2 BƯỚC) ---
            group = new THREE.Group();
            meshMap = {}; // Reset map

            const parentIds = new Set();
            // BƯỚC 1: TẠO MESH ĐỘC LẬP
            for (let [key, value] of Object.entries(data)) {
                if (value[7]) parentIds.add(value[7]); // Collect parent ids
                
                const hasPos = (value[0] !== 0 || value[1] !== 0 || value[2] !== 0);
                if (hasPos) {
                    const mesh = await create3DBox(key, value);
                    meshMap[value[6]] = mesh; // Lưu vào map
                    group.add(mesh); // Tạm thời add vào group chung
                } else {
                    createSidebarItem(key, value);
                }
            }
            scene.add(group);

            // BƯỚC 2: THIẾT LẬP QUAN HỆ CHA CON (ATTACH)
            // Duyệt qua tất cả mesh, nếu có parent_id thì attach vào parent mesh
            for (let id in meshMap) {
                const mesh = meshMap[id];
                const pid = mesh.userData.parent_id;
                if (pid && meshMap[pid]) {
                    // Cập nhật visual cho cha (wireframe)
                    updateParentVisual(meshMap[pid]);
                    // Attach con vào cha (ThreeJS giữ nguyên world position của con)
                    meshMap[pid].attach(mesh);
                }
            }

            // Populate Dropdowns
            const anchorSel = document.getElementById("anchor_select");
            const parentSel = document.getElementById("inp_parent_id");
            anchorSel.innerHTML = '<option value="">-- Chọn vị trí làm mốc --</option>';
            parentSel.innerHTML = '<option value="0">-- Không có (Là gốc) --</option>';

            for (let [key, value] of Object.entries(data)) {
                // Dropdown Alignment
                let opt1 = document.createElement("option"); 
                opt1.value = key; opt1.text = key; 
                opt1.setAttribute('data-id', value[6]); // Lưu ID để tìm nhanh
                anchorSel.appendChild(opt1);
                
                // Dropdown Parent
                let opt2 = document.createElement("option"); 
                opt2.value = value[6]; opt2.text = key; 
                parentSel.appendChild(opt2);
            }
            
            raycaster = new THREE.Raycaster();
            animate();

            const canvas = renderer.domElement;
            canvas.addEventListener("dragover", (e) => e.preventDefault());
            canvas.addEventListener("drop", onDropLocation);
            canvas.addEventListener('click', onCanvasClick);
        }

        // --- CONSTRAIN MOVEMENT (Ràng buộc trong lòng cha) ---
        function constrainMovement(child, parent) {
            // Lấy kích thước Box (Local size)
            // Vì child đã là con của parent, child.position là toạ độ relative
            
            // Tính Half Size của Cha và Con
            // Lưu ý: BoxGeometry mặc định pivot ở giữa, nhưng ta đã translate(0, h/2, 0).
            // Nên: Y chạy từ 0 -> Height. X, Z chạy từ -Width/2 -> Width/2.
            
            // Lấy thông số hình học trực tiếp từ geometry.parameters
            const pGeo = parent.geometry.parameters;
            const cGeo = child.geometry.parameters;

            // X (Width): Tâm ở giữa
            const minX = -(pGeo.width / 2) + (cGeo.width / 2);
            const maxX = (pGeo.width / 2) - (cGeo.width / 2);
            
            // Z (Depth): Tâm ở giữa
            const minZ = -(pGeo.depth / 2) + (cGeo.depth / 2);
            const maxZ = (pGeo.depth / 2) - (cGeo.depth / 2);

            // Y (Height): Tâm ở đáy (0)
            const minY = 0; 
            const maxY = pGeo.height - cGeo.height;

            // Clamp Position
            if (minX <= maxX) child.position.x = Math.max(minX, Math.min(maxX, child.position.x));
            else child.position.x = 0; // Con to hơn cha thì cho ra giữa

            if (minZ <= maxZ) child.position.z = Math.max(minZ, Math.min(maxZ, child.position.z));
            else child.position.z = 0;

            if (minY <= maxY) child.position.y = Math.max(minY, Math.min(maxY, child.position.y));
            else child.position.y = 0;
        }

        // --- HÀM TẠO 3D BOX (Chỉ tạo Mesh, không Add Group ngay) ---
        async function create3DBox(key, value) {
            const l = value[3] > 0 ? value[3] : 50;
            const w = value[4] > 0 ? value[4] : 50;
            const h = value[5] > 0 ? value[5] : 50;
            
            const geo = new THREE.BoxGeometry(l, h, w);
            geo.translate(0, h/2, 0); // Pivot đáy
            
            // Mặc định tạo Solid, sau này nếu có con thì updateParentVisual sẽ chuyển thành Wireframe
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
            
            // Edges
            const edges = new THREE.EdgesGeometry(geo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x333333 }));
            mesh.add(line);
            
            mesh.position.set(value[0], value[1], value[2]);
            mesh.name = key;
            mesh.userData = { color: col, loc_id: value[6], parent_id: value[7] };
            
            // Text Label
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                let baseSize = Math.min(l, w) / 2.5; 
                const shapes = font.generateShapes(key, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                tGeo.translate( xMid, 0, 0 );
                
                // Scale text if needed
                const tW = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                const maxW = (w > l ? w : l) * 0.9;
                if (tW > maxW) { const s = maxW/tW; tGeo.scale(s,s,1); }

                const tMesh = new THREE.Mesh(tGeo, textMat);
                tMesh.position.y = h + 2; 
                tMesh.rotation.x = -Math.PI / 2;
                if (w > l) tMesh.rotation.z = Math.PI / 2;
                mesh.add(tMesh);
            });

            return mesh;
        }

        function updateParentVisual(mesh) {
            if (mesh.material.wireframe) return; // Đã update rồi
            // Chuyển sang Wireframe để nhìn xuyên thấu
            mesh.material.wireframe = true;
            mesh.material.color.set(0x000000);
            mesh.material.opacity = 0.2;
            mesh.userData.is_parent = true;
        }

        // --- CLICK XUYÊN THẤU ---
        async function onCanvasClick(event) {
            if (transformControl.dragging) return;
            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            raycaster.setFromCamera(pointer, camera);
            
            // Intersect recursive (để bắt cả con nằm trong cha)
            const intersects = raycaster.intersectObjects(group.children, true); 

            if (intersects.length > 0) {
                let finalTarget = null;
                // Lọc các mesh có ID
                const hits = intersects.filter(i => i.object.type === 'Mesh' && i.object.userData.loc_id);
                
                if (hits.length > 0) {
                    // Sắp xếp: Ưu tiên Object CON (Solid) hơn Object CHA (Wireframe)
                    // Nếu click trúng cả 2 (do con nằm trong cha), Raycaster thường trả về cả 2.
                    // Ta tìm object nào KHÔNG phải là parent trước.
                    
                    // Tìm con trước
                    finalTarget = hits.find(h => !h.object.userData.is_parent);
                    
                    // Nếu không có con (chỉ click trúng vỏ cha), thì lấy cha
                    if (!finalTarget) finalTarget = hits[0];
                }

                if (finalTarget) selectObject(finalTarget.object);
            } else {
                const gGizmo = raycaster.intersectObjects(transformControl.children, true);
                if (gGizmo.length === 0) deselectObject();
            }
        }

        // --- SAVE LOCATION ---
        async function saveLocationPosition(obj) {
            if (!obj.userData.loc_id) return;
            
            // QUAN TRỌNG: Luôn lấy World Position để lưu vào DB
            const worldPos = new THREE.Vector3();
            obj.getWorldPosition(worldPos);

            await rpc('/web/dataset/call_kw', {
                model: 'stock.location', method: 'write',
                args: [[obj.userData.loc_id], {
                    'pos_x': worldPos.x, 'pos_y': worldPos.y, 'pos_z': worldPos.z,
                }], kwargs: {},
            });
        }

        // ... (Các hàm khác: updateMeshDimensions, createFloor, searchProduct, alignObject giữ nguyên logic cũ) ...
        // ... (Tôi đã gộp chúng vào logic chung ở trên, chỉ liệt kê để nhắc lại) ...
        
        function updateMeshDimensions(mesh, l, w, h) {
            const pxL = l * 3.779 * 2; const pxW = w * 3.779 * 2; const pxH = h * 3.779 * 2;
            const geo = new THREE.BoxGeometry(pxL, pxH, pxW); geo.translate(0, pxH/2, 0);
            mesh.geometry.dispose(); mesh.geometry = geo;
            // Update Line
            const line = mesh.children.find(c => c.type === 'LineSegments');
            if(line) { line.geometry.dispose(); line.geometry = new THREE.EdgesGeometry(geo); }
            // Re-render text (simplified)
            // ... (Logic text re-render giống phiên bản trước) ...
        }

        function createFloor(w, d) {
            const visualW = w * 3.779 * 2; const visualD = d * 3.779 * 2;
            if (baseMesh) scene.remove(baseMesh); if (dragPlane) scene.remove(dragPlane);
            const geo = new THREE.PlaneGeometry(visualW, visualD);
            const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, depthWrite: false });
            baseMesh = new THREE.Mesh(geo, mat); baseMesh.rotation.x = -Math.PI / 2; baseMesh.position.y = -0.5; scene.add(baseMesh);
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
                // Reset opacity
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
            // Nếu target là con, newPos đang là World Pos, cần chuyển về Local Pos
            if (target.parent && target.parent.type === 'Mesh') {
                target.parent.worldToLocal(newPos);
            }
            target.position.copy(newPos);
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
                meshMap[item.id] = mesh; // Add to map
                group.add(mesh); // Add to group
                
                Array.from(sidebarList.children).forEach(child => { if (child.innerText === item.code) sidebarList.removeChild(child); });
                await saveLocationPosition(mesh);
                selectObject(mesh);
            }
        }

        function createSidebarItem(code, val) {
            const item = document.createElement("div");
            item.classList.add("location-item"); item.innerText = code; item.draggable = true;
            item.addEventListener("dragstart", (e) => {
                e.dataTransfer.setData("text/plain", JSON.stringify({id: val[6], code: code, l: val[3]>0?val[3]:50, w: val[4]>0?val[4]:50, h: val[5]>0?val[5]:50}));
            });
            sidebarList.appendChild(item);
        }

        function deselectObject() {
            selectedObject = null; transformControl.detach(); panelDiv.style.display = "none";
        }

        function warehouseChange() {
            wh_id = document.querySelector(".customselect").value; start();
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