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
        let anchorObject = null; // Vị trí GỐC để căn chỉnh
        
        // Cấu hình sàn mặc định
        let floorWidth = 2000;
        let floorDepth = 2000;
        let baseMesh, dragPlane;

        const pointer = new THREE.Vector2();

        // Lấy dữ liệu kho
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

        // 2. Nút Thoát
        var closeDiv = document.createElement("button");
        closeDiv.classList.add("closeBtn");
        closeDiv.innerHTML = "&times;";
        closeDiv.style.zIndex = "1001";
        closeDiv.title = "Thoát";
        closeDiv.onclick = () => window.location.reload();

        // 3. Thanh Tìm kiếm (Search Bar)
        const searchDiv = document.createElement("div");
        searchDiv.classList.add("search-container");
        searchDiv.innerHTML = `
            <i class="fa fa-search" style="color:#666;"></i>
            <input type="text" id="product_search_inp" placeholder="Tìm sản phẩm..." style="border:none; outline:none; margin-left:5px;">
            <button id="btn_do_search" class="btn btn-sm btn-primary" style="border-radius:50%; width:30px; height:30px; padding:0;"><i class="fa fa-arrow-right"></i></button>
        `;

        // 4. Chú thích màu (Legend)
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

        // 5. Sidebar (Drag Source + Floor Config)
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

        // 6. SELECTION PANEL (Thông tin + Align Tool)
        const panelDiv = document.createElement("div");
        panelDiv.classList.add("selection-panel");
        // Style cho panel rộng hơn chút để chứa nhiều nút
        panelDiv.style.width = "340px";
        panelDiv.innerHTML = `
            <h5>
                <span id="panel_loc_name" style="color:#007bff; font-weight:bold;">Tên Vị Trí</span>
                <button class="btn-close-panel" id="btn_close_panel" style="cursor:pointer; float:right;">&times;</button>
            </h5>
            
            <div class="edit-section" style="background:#f0f8ff; border:1px solid #cce5ff; padding:5px; margin-bottom:10px; border-radius:4px;">
                <h6 style="font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;">
                    <i class="fa fa-crosshairs"></i> Căn chỉnh vị trí
                </h6>
                <div style="font-size:11px; margin-bottom:5px; display:flex; justify-content:space-between; align-items:center;">
                    <span>Gốc: <b id="anchor_name" style="color:#d63384;">(Chưa chọn)</b></span>
                    <button id="btn_set_anchor" class="btn btn-xs btn-outline-primary" style="font-size:10px;">Chọn làm Gốc</button>
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:3px;">
                    <button class="btn btn-light btn-sm btn-align" data-dir="left" title="Xếp sang Trái"><i class="fa fa-arrow-left"></i> Trái</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="top" title="Chồng lên trên"><i class="fa fa-arrow-up"></i> Trên</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="right" title="Xếp sang Phải"><i class="fa fa-arrow-right"></i> Phải</button>
                    
                    <button class="btn btn-light btn-sm btn-align" data-dir="front" title="Xếp ra Trước"><i class="fa fa-arrow-down"></i> Trước</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="bottom" title="Đặt xuống Dưới"><i class="fa fa-arrow-down"></i> Dưới</button>
                    <button class="btn btn-light btn-sm btn-align" data-dir="back" title="Xếp ra Sau"><i class="fa fa-arrow-up"></i> Sau</button>
                </div>
            </div>

            <div class="edit-section">
                <h6 style="font-size:12px; font-weight:bold; background:#eee; padding:3px;">Thông số kỹ thuật</h6>
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
                <button class="btn btn-primary btn-sm w-100" id="btn_save_changes" style="margin-top:5px;">Lưu</button>
            </div>

            <div class="product-list" style="margin-top:10px; border-top:1px solid #eee;">
                <h6 style="font-size:12px; font-weight:bold; margin-top:5px;">Sản phẩm</h6>
                <div id="product_table_container" style="max-height:80px; overflow-y:auto;">
                    <table>
                        <thead><tr><th>Tên</th><th style="text-align:right;">SL</th></tr></thead>
                        <tbody id="product_list_body"></tbody>
                    </table>
                </div>
                <div id="product_empty_msg" style="display:none; text-align:center; font-size:11px; color:#999;">(Trống)</div>
            </div>

            <div class="picking-list" style="margin-top:10px; border-top:1px solid #eee;">
                <h6 style="font-size:12px; font-weight:bold; margin-top:5px;">Hoạt động kho</h6>
                <div id="picking_list_container" style="max-height:80px; overflow-y:auto;"></div>
                <div id="picking_empty_msg" style="display:none; text-align:center; font-size:11px; color:#999;">(Không có phiếu)</div>
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

            // DOM Insertion
            $(self.rootRef.el).find('.o_list_renderer').addClass('d-none');
            $(self.rootRef.el).find('canvas').remove();
            
            const content = $(self.rootRef.el).find('.o_content');
            content.append(renderer.domElement);
            content.append(select);
            content.append(colorDiv);
            content.append(closeDiv);
            content.append(searchDiv);
            content.append(sidebarDiv);
            content.append(panelDiv);

            // Event Listeners UI
            document.querySelector(".customselect")?.addEventListener("change", warehouseChange);
            document.querySelector("#btn_close_panel").addEventListener("click", deselectObject);
            document.querySelector("#btn_update_floor").addEventListener("click", updateFloorSize);
            
            // Search Logic
            const btnSearch = document.getElementById("btn_do_search");
            const inpSearch = document.getElementById("product_search_inp");
            btnSearch.addEventListener("click", () => searchProduct(inpSearch.value));
            inpSearch.addEventListener("keyup", (e) => { if (e.key === 'Enter') searchProduct(inpSearch.value); });

            // Alignment Logic (Vấn đề 1)
            document.querySelector("#btn_set_anchor").addEventListener("click", () => {
                if(selectedObject) {
                    anchorObject = selectedObject;
                    document.getElementById("anchor_name").innerText = selectedObject.name;
                }
            });

            document.querySelectorAll(".btn-align").forEach(btn => {
                btn.addEventListener("click", async () => {
                    if (!selectedObject || !anchorObject) { alert("Chọn vị trí Gốc trước!"); return; }
                    if (selectedObject === anchorObject) return;
                    alignObject(selectedObject, anchorObject, btn.dataset.dir);
                    await saveLocationPosition(selectedObject);
                    transformControl.attach(selectedObject);
                });
            });

            // Save Changes Logic
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
                    model: 'stock.location', method: 'write',
                    args: [[locId], { 'length': l, 'width': w, 'height': h, 'max_capacity': cap, 'pos_x': px, 'pos_y': py, 'pos_z': pz }],
                    kwargs: {},
                });
                
                selectedObject.position.set(px, py, pz);
                updateMeshDimensions(selectedObject, l, w, h);
                transformControl.attach(selectedObject);
                alert("Đã lưu!");
            });

            // ThreeJS Controls
            controls = new THREE.OrbitControls(camera, renderer.domElement);
            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value;
                if (!event.value && transformControl.object) {
                    const obj = transformControl.object;
                    document.getElementById('inp_pos_x').value = Math.round(obj.position.x);
                    document.getElementById('inp_pos_y').value = Math.round(obj.position.y);
                    document.getElementById('inp_pos_z').value = Math.round(obj.position.z);
                    saveLocationPosition(obj);
                }
            });
            scene.add(transformControl);

            // Floor
            createFloor(floorWidth, floorDepth);

            // Init Objects & Check Hierarchy (Vấn đề 2)
            group = new THREE.Group();
            
            // Tìm tất cả Parent ID để biết cái nào là cha
            const parentIds = new Set();
            for (let val of Object.values(data)) {
                // val[7] là parent_id (Lưu ý: phải update Python để trả về index 7)
                if (val[7]) parentIds.add(val[7]); 
            }

            for (let [key, value] of Object.entries(data)) {
                const hasPos = (value[0] !== 0 || value[1] !== 0 || value[2] !== 0);
                if (hasPos) {
                    const isParent = parentIds.has(value[6]); // Check ID có trong list parent không
                    await create3DBox(key, value, isParent);
                } else {
                    createSidebarItem(key, value);
                }
            }
            scene.add(group);
            
            raycaster = new THREE.Raycaster();
            animate();

            const canvas = renderer.domElement;
            canvas.addEventListener("dragover", (e) => e.preventDefault());
            canvas.addEventListener("drop", onDropLocation);
            canvas.addEventListener('click', onCanvasClick);
        }

        // --- HÀM CĂN CHỈNH (ALIGNMENT) ---
        function alignObject(target, anchor, direction) {
            const boxT = new THREE.Box3().setFromObject(target);
            const boxA = new THREE.Box3().setFromObject(anchor);
            const sizeT = new THREE.Vector3(); boxT.getSize(sizeT);
            const sizeA = new THREE.Vector3(); boxA.getSize(sizeA);
            const centerA = new THREE.Vector3(); boxA.getCenter(centerA);
            
            const newPos = centerA.clone();
            const margin = 2; // Khoảng hở nhỏ

            switch(direction) {
                case 'right': 
                    newPos.x = centerA.x + (sizeA.x/2) + (sizeT.x/2) + margin; 
                    newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2); // Đáy bằng nhau
                    newPos.z = centerA.z;
                    break;
                case 'left': 
                    newPos.x = centerA.x - (sizeA.x/2) - (sizeT.x/2) - margin; 
                    newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2);
                    newPos.z = centerA.z;
                    break;
                case 'top': 
                    newPos.y = centerA.y + (sizeA.y/2) + (sizeT.y/2); 
                    newPos.x = centerA.x; newPos.z = centerA.z;
                    break;
                case 'bottom': 
                    newPos.y = centerA.y - (sizeA.y/2) - (sizeT.y/2); 
                    newPos.x = centerA.x; newPos.z = centerA.z;
                    break;
                case 'front': 
                    newPos.z = centerA.z + (sizeA.z/2) + (sizeT.z/2) + margin; 
                    newPos.x = centerA.x; 
                    newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2);
                    break;
                case 'back': 
                    newPos.z = centerA.z - (sizeA.z/2) - (sizeT.z/2) - margin; 
                    newPos.x = centerA.x; 
                    newPos.y = centerA.y + (sizeT.y/2 - sizeA.y/2);
                    break;
            }
            target.position.copy(newPos);
        }

        // --- TÌM SẢN PHẨM ---
        async function searchProduct(keyword) {
            if (!keyword) {
                group.children.forEach(mesh => {
                    if (mesh.userData.color) {
                        mesh.material.color.set(mesh.userData.color);
                        mesh.material.opacity = mesh.userData.is_parent ? 0.1 : (mesh.userData.color === 0x8c8c8c ? 0.5 : 0.8);
                    }
                });
                return;
            }
            const locCodes = await rpc('/3Dstock/search_product', { keyword: keyword, wh_id: wh_id });
            if (locCodes.length === 0) { alert("Không thấy!"); return; }

            let first = null;
            group.children.forEach(mesh => {
                if (locCodes.includes(mesh.name)) {
                    mesh.material.color.set(0xff00ff); // Highlight màu hồng
                    mesh.material.opacity = 1;
                    if (!first) first = mesh;
                } else {
                    if (mesh.userData.color) {
                         mesh.material.color.set(0xeeeeee);
                         mesh.material.opacity = 0.1;
                    }
                }
            });
            if(first) { controls.target.copy(first.position); controls.update(); }
        }

        // --- CÁC HÀM XỬ LÝ SÀN (FLOOR) ---
        function createFloor(w, d) {
            const visualW = w * 3.779 * 2; 
            const visualD = d * 3.779 * 2;
            if (baseMesh) scene.remove(baseMesh);
            if (dragPlane) scene.remove(dragPlane);
            
            const geometry = new THREE.PlaneGeometry(visualW, visualD);
            const material = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, depthWrite: false });
            baseMesh = new THREE.Mesh(geometry, material);
            baseMesh.rotation.x = -Math.PI / 2;
            baseMesh.position.y = -0.5;
            scene.add(baseMesh);

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
                // Ưu tiên chọn object con (Mesh)
                let target = intersects.find(r => r.object.type === 'Mesh' && r.object.userData.loc_id);
                // Nếu click vào text/line, tìm parent
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
                model: 'stock.location', method: 'read',
                args: [[locId], ['length', 'width', 'height', 'max_capacity']], kwargs: {}
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
            tbody.innerHTML = "<tr><td colspan='2' style='text-align:center;'>...</td></tr>";
            await rpc('/3Dstock/data/product', { 'loc_code': mesh.name }).then(prodData => {
                tbody.innerHTML = "";
                const list = prodData.product_list || [];
                if (list.length === 0) emptyMsg.style.display = "block";
                else {
                    emptyMsg.style.display = "none";
                    list.forEach(p => {
                        const tr = document.createElement("tr");
                        tr.innerHTML = `<td>${p[0]}</td><td style="text-align:right; font-weight:bold;">${p[1]}</td>`;
                        tbody.appendChild(tr);
                    });
                }
            });

            // Load Pickings
            const pickDiv = document.getElementById("picking_list_container");
            const pickEmpty = document.getElementById("picking_empty_msg");
            pickDiv.innerHTML = "<div style='text-align:center;'>...</div>";
            await rpc('/3Dstock/data/pickings', { 'loc_code': mesh.name }).then(picks => {
                pickDiv.innerHTML = "";
                if (picks.length === 0) pickEmpty.style.display = "block";
                else {
                    pickEmpty.style.display = "none";
                    picks.forEach(p => {
                        let cl = p.type==="Nhập hàng"?"#28a745":p.type==="Xuất hàng"?"#dc3545":"#ffc107";
                        const div = document.createElement("div");
                        div.style.borderBottom = "1px solid #eee"; div.style.padding = "5px";
                        div.innerHTML = `<div style="font-weight:bold; display:flex; justify-content:space-between;"><span>${p.name}</span><span style="color:${cl}; font-size:10px;">${p.type}</span></div><div style="font-size:10px; color:#666;">${p.origin||''} - ${p.state}</div>`;
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
                // Mặc định tạo object mới không phải là cha (isParent=false)
                const newMesh = await create3DBox(itemData.code, [point.x, 0, point.z, itemData.l, itemData.w, itemData.h, itemData.id], false);
                
                Array.from(sidebarList.children).forEach(child => {
                    if (child.innerText === itemData.code) sidebarList.removeChild(child);
                });

                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location', method: 'write',
                    args: [[itemData.id], {
                        'pos_x': point.x, 'pos_y': 0, 'pos_z': point.z,
                        'length': itemData.l / (3.779 * 2), 'width': itemData.w / (3.779 * 2), 'height': itemData.h / (3.779 * 2),
                    }], kwargs: {},
                });
                selectObject(newMesh);
            }
        }

        // --- CREATE 3D BOX (CHA/CON SUPPORT) ---
        async function create3DBox(key, value, isParent) {
            const l = value[3] > 0 ? value[3] : 50;
            const w = value[4] > 0 ? value[4] : 50;
            const h = value[5] > 0 ? value[5] : 50;
            
            const geo = new THREE.BoxGeometry(l, h, w);
            geo.translate(0, h/2, 0);
            
            let col = 0x8c8c8c; let op = 0.5;
            let material;

            if (isParent) {
                // CHA: Wireframe / Trong suốt
                material = new THREE.MeshBasicMaterial({ color: 0x000000, wireframe: true, transparent:true, opacity: 0.1 });
            } else {
                // CON: Tính màu
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
                material = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: op });
            }

            const mesh = new THREE.Mesh(geo, material);
            const edges = new THREE.EdgesGeometry(geo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            
            mesh.position.set(value[0], value[1], value[2]);
            line.position.set(0,0,0); 
            
            mesh.name = key;
            mesh.userData = { color: col, loc_id: value[6], is_parent: isParent };
            mesh.add(line); 
            
            // Text Label
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                // Scale text nhỏ lại nếu là con
                let textScale = isParent ? 2.5 : 3.0;
                let baseSize = Math.min(l, w) / textScale; 
                const shapes = font.generateShapes(key, baseSize);
                const tGeo = new THREE.ShapeGeometry(shapes);
                
                tGeo.computeBoundingBox();
                const xMid = - 0.5 * ( tGeo.boundingBox.max.x - tGeo.boundingBox.min.x );
                tGeo.translate( xMid, 0, 0 );
                
                // Auto fit
                let containerSize = (w > l) ? w : l;
                const textWidth = tGeo.boundingBox.max.x - tGeo.boundingBox.min.x;
                const maxAllowed = containerSize * 0.9;
                if (textWidth > maxAllowed) {
                    const scaleFactor = maxAllowed / textWidth;
                    tGeo.scale(scaleFactor, scaleFactor, 1);
                }

                const textMesh = new THREE.Mesh(tGeo, textMat);
                textMesh.position.y = h + 2; 
                textMesh.rotation.x = -Math.PI / 2;
                if (w > l) textMesh.rotation.z = Math.PI / 2;
                
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
            
            const oldLine = mesh.children.find(c => c.type === 'LineSegments');
            if(oldLine) mesh.remove(oldLine);
            const edges = new THREE.EdgesGeometry(newGeo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            mesh.add(line);
            
            const oldText = mesh.children.find(c => c.type === 'Mesh' && c !== line); 
            if (oldText) mesh.remove(oldText);
            
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                let containerSize = (pxW > pxL) ? pxW : pxL;
                let textScale = mesh.userData.is_parent ? 2.5 : 3.0;
                let baseSize = Math.min(pxL, pxW) / textScale;
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