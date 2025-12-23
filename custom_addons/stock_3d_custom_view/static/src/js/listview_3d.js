/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ensureJQuery } from '@web/core/ensure_jquery';
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";

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
        
        // Cấu hình sàn mặc định
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
        
        // 1. Dropdown Warehouse
        var select = document.createElement("select");
        select.classList.add("customselect");
        wh_data.forEach(w => {
            var opt = document.createElement("option");
            opt.value = w[0]; opt.text = w[1];
            select.appendChild(opt);
        });

        // 2. Close Button
        var closeDiv = document.createElement("button");
        closeDiv.classList.add("closeBtn");
        closeDiv.innerHTML = "&times;";
        closeDiv.style.zIndex = "1001";
        closeDiv.title = "Thoát";
        closeDiv.onclick = () => window.location.reload();

        // 3. Legend Colors
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

        // 4. Sidebar (Drag Source + Floor Config)
        const sidebarDiv = document.createElement("div");
        sidebarDiv.classList.add("location-sidebar");
        
        sidebarDiv.innerHTML = `
            <div style="padding-bottom:10px; border-bottom:1px solid #ddd; margin-bottom:10px;">
                <h6 style="font-weight:bold; font-size:13px; text-align:center;">Cấu hình Sàn (m)</h6>
                <div style="display:flex; gap:5px; justify-content:center;">
                    <input type="number" id="floor_w_cfg" value="500" placeholder="Rộng" style="width:60px; font-size:12px;">
                    <span style="align-self:center;">x</span>
                    <input type="number" id="floor_d_cfg" value="500" placeholder="Dài" style="width:60px; font-size:12px;">
                    <button id="btn_update_floor" class="btn btn-sm btn-secondary" style="font-size:10px;">Vẽ</button>
                </div>
            </div>
            <h6 style="text-align:center; font-weight:bold; font-size:13px; margin-bottom:5px;">Chưa Setup</h6>
        `;
        
        const sidebarList = document.createElement("div");
        sidebarList.style.maxHeight = "55vh"; 
        sidebarList.style.overflowY = "auto";
        sidebarDiv.appendChild(sidebarList);

        // 5. SELECTION PANEL
        const panelDiv = document.createElement("div");
        panelDiv.classList.add("selection-panel");
        panelDiv.innerHTML = `
            <h5>
                <span id="panel_loc_name" style="color:#007bff; font-weight:bold;">Tên Vị Trí</span>
                <button class="btn-close-panel" id="btn_close_panel" style="cursor:pointer; float:right;">&times;</button>
            </h5>
            
            <div class="edit-section">
                <h6 style="font-size:12px; font-weight:bold; margin-top:5px; background:#eee; padding:3px;">Kích thước (m) & Sức chứa</h6>
                <div class="input-group"><label>Dài</label> <input type="number" id="inp_l" step="0.1"></div>
                <div class="input-group"><label>Rộng</label> <input type="number" id="inp_w" step="0.1"></div>
                <div class="input-group"><label>Cao</label> <input type="number" id="inp_h" step="0.1"></div>
                <div class="input-group"><label>Sức chứa</label> <input type="number" id="inp_cap"></div>
            </div>

            <div class="edit-section" style="margin-top:5px;">
                <h6 style="font-size:12px; font-weight:bold; margin-top:5px; background:#eee; padding:3px;">Tọa độ (X, Y, Z)</h6>
                <div class="input-group"><label>Pos X</label> <input type="number" id="inp_pos_x" step="1"></div>
                <div class="input-group"><label>Pos Y</label> <input type="number" id="inp_pos_y" step="1"></div>
                <div class="input-group"><label>Pos Z</label> <input type="number" id="inp_pos_z" step="1"></div>
            </div>
            
            <button class="btn btn-primary btn-sm w-100" id="btn_save_changes" style="margin-top:8px;">
                <i class="fa fa-save"></i> Lưu Cài Đặt
            </button>

            <div class="product-list">
                <h6 style="font-size:12px; font-weight:bold; margin-top:10px; border-bottom:1px solid #eee;">Sản phẩm</h6>
                <div id="product_table_container" style="max-height:120px; overflow-y:auto;">
                    <table>
                        <thead><tr><th>Tên</th><th style="text-align:right;">SL</th></tr></thead>
                        <tbody id="product_list_body"></tbody>
                    </table>
                </div>
                <div id="product_empty_msg" style="display:none; text-align:center; font-size:11px; color:#999; padding:5px;">(Trống)</div>
            </div>
        `;

        start();

        async function start() {
            // Load data
            await rpc('/3Dstock/data', { 
                'company_id': user.context.allowed_company_ids[0], 
                'wh_id': wh_id 
            }).then(res => { data = res; });

            sidebarList.innerHTML = "";

            // Scene Init
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xe0e0e0);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 10000);
            camera.position.set(0, 500, 800);

            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight / 1.164);
            renderer.setPixelRatio(window.devicePixelRatio);

            // Clear old DOM
            $(self.rootRef.el).find('.o_list_renderer').addClass('d-none');
            $(self.rootRef.el).find('canvas').remove();
            
            const content = $(self.rootRef.el).find('.o_content');
            content.append(renderer.domElement);
            content.append(select);
            content.append(colorDiv);
            content.append(closeDiv);
            content.append(sidebarDiv);
            content.append(panelDiv);

            // Events Listeners
            document.querySelector(".customselect")?.addEventListener("change", warehouseChange);
            document.querySelector("#btn_close_panel").addEventListener("click", deselectObject);
            document.querySelector("#btn_update_floor").addEventListener("click", updateFloorSize);

            // SAVE BUTTON LOGIC
            document.querySelector("#btn_save_changes").addEventListener("click", async () => {
                if (!selectedObject) return;
                const locId = selectedObject.userData.loc_id;
                
                const l = parseFloat(document.getElementById('inp_l').value) || 0;
                const w = parseFloat(document.getElementById('inp_w').value) || 0;
                const h = parseFloat(document.getElementById('inp_h').value) || 0;
                const cap = parseInt(document.getElementById('inp_cap').value) || 0;
                const px = parseFloat(document.getElementById('inp_pos_x').value) || 0;
                const py = parseFloat(document.getElementById('inp_pos_y').value) || 0;
                const pz = parseFloat(document.getElementById('inp_pos_z').value) || 0;

                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location',
                    method: 'write',
                    args: [[locId], {
                        'length': l, 'width': w, 'height': h, 'max_capacity': cap,
                        'pos_x': px, 'pos_y': py, 'pos_z': pz
                    }],
                    kwargs: {},
                });
                
                // Update Visuals
                selectedObject.position.set(px, py, pz);
                updateMeshDimensions(selectedObject, l, w, h);
                transformControl.attach(selectedObject);
                // alert("Đã lưu thành công!");
            });

            // THREE JS CONTROLS
            controls = new THREE.OrbitControls(camera, renderer.domElement);
            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value;
                if (!event.value && transformControl.object) {
                    const obj = transformControl.object;
                    // Update Panel Inputs
                    document.getElementById('inp_pos_x').value = Math.round(obj.position.x);
                    document.getElementById('inp_pos_y').value = Math.round(obj.position.y);
                    document.getElementById('inp_pos_z').value = Math.round(obj.position.z);
                    saveLocationPosition(obj);
                }
            });
            scene.add(transformControl);

            // INIT FLOOR
            createFloor(floorWidth, floorDepth);

            // INIT OBJECTS
            group = new THREE.Group();
            for (let [key, value] of Object.entries(data)) {
                // value: [x, y, z, l, w, h, id]
                const hasPos = (value[0] !== 0 || value[1] !== 0 || value[2] !== 0);
                if (hasPos) await create3DBox(key, value);
                else createSidebarItem(key, value);
            }
            scene.add(group);
            
            raycaster = new THREE.Raycaster();
            animate();

            // DOM Events
            const canvas = renderer.domElement;
            canvas.addEventListener("dragover", (e) => e.preventDefault());
            canvas.addEventListener("drop", onDropLocation);
            canvas.addEventListener('click', onCanvasClick);
        }

        // --- CÁC HÀM XỬ LÝ SÀN (FLOOR) ---
        function createFloor(w, d) {
            const visualW = w * 3.779 * 2; 
            const visualD = d * 3.779 * 2;

            if (baseMesh) scene.remove(baseMesh);
            if (dragPlane) scene.remove(dragPlane);

            // Sàn hiển thị (TRẮNG TRƠN - KHÔNG LƯỚI)
            const geometry = new THREE.PlaneGeometry(visualW, visualD);
            const material = new THREE.MeshBasicMaterial({ 
                color: 0xffffff, side: THREE.DoubleSide, 
                depthWrite: false 
            });
            baseMesh = new THREE.Mesh(geometry, material);
            baseMesh.rotation.x = -Math.PI / 2;
            baseMesh.position.y = -0.5;
            scene.add(baseMesh);

            // Sàn vô hình (để bắt sự kiện Drop)
            const planeGeo = new THREE.PlaneGeometry(10000, 10000); 
            const planeMat = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
            dragPlane = new THREE.Mesh(planeGeo, planeMat);
            dragPlane.rotation.x = -Math.PI / 2;
            scene.add(dragPlane);
        }

        function updateFloorSize() {
            const w = parseFloat(document.getElementById('floor_w_cfg').value) || 500;
            const d = parseFloat(document.getElementById('floor_d_cfg').value) || 500;
            createFloor(w, d);
        }

        // --- XỬ LÝ CLICK ---
        async function onCanvasClick(event) {
            if (transformControl.dragging) return;
            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            raycaster.setFromCamera(pointer, camera);
            const intersects = raycaster.intersectObjects(group.children, true); 

            if (intersects.length > 0) {
                let target = intersects.find(r => r.object.type === 'Mesh' && r.object.userData.loc_id);
                if (!target) {
                    let childHit = intersects.find(r => r.object.parent && r.object.parent.userData.loc_id);
                    if (childHit) target = { object: childHit.object.parent };
                }

                if (target) selectObject(target.object);
            } else {
                const gizmoIntersects = raycaster.intersectObjects(transformControl.children, true);
                if (gizmoIntersects.length === 0) deselectObject();
            }
        }

        async function selectObject(mesh) {
            if (selectedObject === mesh) return;
            selectedObject = mesh;
            transformControl.attach(mesh);
            panelDiv.style.display = "block";
            
            document.getElementById("panel_loc_name").innerText = mesh.name;
            document.getElementById('inp_pos_x').value = Math.round(mesh.position.x);
            document.getElementById('inp_pos_y').value = Math.round(mesh.position.y);
            document.getElementById('inp_pos_z').value = Math.round(mesh.position.z);

            const locId = mesh.userData.loc_id;
            const res = await rpc('/web/dataset/call_kw', {
                model: 'stock.location',
                method: 'read',
                args: [[locId], ['length', 'width', 'height', 'max_capacity']],
                kwargs: {}
            });
            if (res && res.length > 0) {
                const info = res[0];
                document.getElementById('inp_l').value = info.length;
                document.getElementById('inp_w').value = info.width;
                document.getElementById('inp_h').value = info.height;
                document.getElementById('inp_cap').value = info.max_capacity;
            }

            // Load Products
            const tbody = document.getElementById('product_list_body');
            const emptyMsg = document.getElementById('product_empty_msg');
            tbody.innerHTML = "<tr><td colspan='2' style='text-align:center;'>Đang tải...</td></tr>";
            
            await rpc('/3Dstock/data/product', { 'loc_code': mesh.name }).then(prodData => {
                tbody.innerHTML = "";
                const list = prodData.product_list || [];
                if (list.length === 0) {
                    emptyMsg.style.display = "block";
                } else {
                    emptyMsg.style.display = "none";
                    list.forEach(p => {
                        const tr = document.createElement("tr");
                        tr.innerHTML = `<td>${p[0]}</td><td style="text-align:right; font-weight:bold;">${p[1]}</td>`;
                        tbody.appendChild(tr);
                    });
                }
            });
        }

        function deselectObject() {
            selectedObject = null;
            transformControl.detach();
            panelDiv.style.display = "none";
        }

        // --- CREATE & DROP LOGIC ---

        function createSidebarItem(code, val) {
            const item = document.createElement("div");
            item.classList.add("location-item");
            item.innerText = code;
            item.draggable = true;
            item.addEventListener("dragstart", (e) => {
                const dragData = JSON.stringify({
                    id: val[6], code: code,
                    l: val[3] > 0 ? val[3] : 50, w: val[4] > 0 ? val[4] : 50, h: val[5] > 0 ? val[5] : 50
                });
                e.dataTransfer.setData("text/plain", dragData);
            });
            sidebarList.appendChild(item);
        }

        async function onDropLocation(e) {
            e.preventDefault();
            const rawData = e.dataTransfer.getData("text/plain");
            if (!rawData) return;
            const itemData = JSON.parse(rawData);

            const mouse = new THREE.Vector2();
            mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
            mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;

            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObject(dragPlane);

            if (intersects.length > 0) {
                const point = intersects[0].point;
                // Snap to Y=0
                const newData = [point.x, 0, point.z, itemData.l, itemData.w, itemData.h, itemData.id];
                const newMesh = await create3DBox(itemData.code, newData);
                
                Array.from(sidebarList.children).forEach(child => {
                    if (child.innerText === itemData.code) sidebarList.removeChild(child);
                });

                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location',
                    method: 'write',
                    args: [[itemData.id], {
                        'pos_x': point.x, 'pos_y': 0, 'pos_z': point.z,
                        'length': itemData.l / (3.779 * 2), 
                        'width': itemData.w / (3.779 * 2),
                        'height': itemData.h / (3.779 * 2),
                    }],
                    kwargs: {},
                });
                selectObject(newMesh);
            }
        }

        // --- 3D BOX CREATION (WITH COLOR FIX) ---
        async function create3DBox(key, value) {
            const l = value[3] > 0 ? value[3] : 50;
            const w = value[4] > 0 ? value[4] : 50;
            const h = value[5] > 0 ? value[5] : 50;
            
            const geo = new THREE.BoxGeometry(l, h, w);
            geo.translate(0, h/2, 0);
            
            const edges = new THREE.EdgesGeometry(geo);
            
            let col = 0x8c8c8c; // Mặc định là Xám (Không có hàng)
            let op = 0.5;

            await rpc('/3Dstock/data/quantity', { 'loc_code': key }).then(q => {
                // q = [capacity, load_percentage]
                // Fix Logic Màu:
                if (q[0] > 0) { // Có setup Capacity
                   if (q[1] > 100) { col = 0xcc0000; op = 0.8; } // Quá tải
                   else if (q[1] > 50) { col = 0xe6b800; op = 0.8; } // Sắp đầy
                   else if (q[1] > 0) { col = 0x00802b; op = 0.8; } // Có hàng (Xanh lá)
                   else { col = 0x8c8c8c; op = 0.5; } // Load = 0% -> Xám
                } else { // Không có Capacity
                   if(q[1] == -1) { col = 0x00802b; op = 0.8; } // Có hàng
                   else { col = 0x8c8c8c; op = 0.5; } // Không hàng
                }
            });

            const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: op }));
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            
            mesh.position.set(value[0], value[1], value[2]);
            line.position.set(0,0,0); 
            
            mesh.name = key;
            mesh.userData = { color: col, loc_id: value[6] };
            mesh.add(line); 
            
            // --- TEXT AUTO-FIT ---
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                
                let containerSize = (w > l) ? w : l;
                let baseSize = Math.min(l, w) / 2.5; 
                
                const shapes = font.generateShapes(key, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                
                // Canh giữa text
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                tGeo.translate( xMid, 0, 0 );
                
                // Scale text nếu bị tràn
                const textWidth = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                const maxAllowed = containerSize * 0.9;
                if (textWidth > maxAllowed) {
                    const scaleFactor = maxAllowed / textWidth;
                    tGeo.scale(scaleFactor, scaleFactor, 1);
                }

                const textMesh = new THREE.Mesh(tGeo, textMat);
                textMesh.position.y = h + 2; 
                textMesh.rotation.x = -Math.PI / 2;

                if (w > l) {
                    textMesh.rotation.z = Math.PI / 2;
                }
                
                mesh.add(textMesh);
            });

            group.add(mesh);
            return mesh;
        }

        function updateMeshDimensions(mesh, l, w, h) {
            const pxL = l * 3.779 * 2;
            const pxW = w * 3.779 * 2;
            const pxH = h * 3.779 * 2;
            const newGeo = new THREE.BoxGeometry(pxL, pxH, pxW);
            newGeo.translate(0, pxH/2, 0);
            mesh.geometry.dispose();
            mesh.geometry = newGeo;
            
            // Xóa line cũ tạo line mới
            const oldLine = mesh.children.find(c => c.type === 'LineSegments');
            if(oldLine) mesh.remove(oldLine);
            
            const edges = new THREE.EdgesGeometry(newGeo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            mesh.add(line);
            
            // Re-render Text
            const oldText = mesh.children.find(c => c.type === 'Mesh' && c !== line); 
            if (oldText) mesh.remove(oldText);
            
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                let containerSize = (pxW > pxL) ? pxW : pxL;
                let baseSize = Math.min(pxL, pxW) / 2.5;
                
                const shapes = font.generateShapes(mesh.name, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                tGeo.translate( xMid, 0, 0 );
                
                const textWidth = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                const maxAllowed = containerSize * 0.9;
                if (textWidth > maxAllowed) {
                    const scaleFactor = maxAllowed / textWidth;
                    tGeo.scale(scaleFactor, scaleFactor, 1);
                }

                const textMesh = new THREE.Mesh(tGeo, textMat);
                textMesh.position.y = pxH + 2;
                textMesh.rotation.x = -Math.PI / 2;
                if (pxW > pxL) textMesh.rotation.z = Math.PI / 2;
                mesh.add(textMesh);
            });
        }

        async function saveLocationPosition(obj) {
            if (!obj.userData.loc_id) return;
            await rpc('/web/dataset/call_kw', {
                model: 'stock.location',
                method: 'write',
                args: [[obj.userData.loc_id], {
                    'pos_x': obj.position.x, 'pos_y': obj.position.y, 'pos_z': obj.position.z,
                }],
                kwargs: {},
            });
        }

        function warehouseChange() {
            wh_id = document.querySelector(".customselect").value;
            start();
        }

        function animate() {
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }
    }
}

registry.category("views").add("3d_button_in_stock", {
    ...listView,
    Controller: Stock3DController,
    buttonTemplate: 'stock_3d_custom_view.ListView.Buttons'
});