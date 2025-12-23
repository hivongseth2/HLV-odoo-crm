/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, onMounted, onPatched, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS, loadCSS } from "@web/core/assets";
import { cookie } from "@web/core/browser/cookie";
import { ensureJQuery } from '@web/core/ensure_jquery';
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { Dialog } from "@web/core/dialog/dialog";

// Component Dialog hiển thị danh sách sản phẩm
export class CustomDialog extends Component {
    static components = { Dialog };
    static template = 'stock_3d_custom_view.ViewLocationData';
    get getData() { return this.props.data; }
}

export class Stock3DController extends ListController {
    // --- SỬA LỖI: Thêm hàm setup để khai báo service dialog ---
    setup() {
        super.setup();
        this.dialog = useService("dialog"); // Khởi tạo service dialog
        this.orm = useService("orm");
    }

    async open3DView(ev) {
        var self = this;
        await ensureJQuery();
        
        // --- VARIABLES ---
        var wh_data, data;
        let controls, renderer, clock, scene, camera, raycaster;
        let transformControl; // Biến kéo thả
        var group;
        var wh_id;
        let selectedObject = null; // Object đang được chọn

        // Raycaster Mouse
        const pointer = new THREE.Vector2();
        
        // Mặt sàn tàng hình (để Drop)
        const planeGeometry = new THREE.PlaneGeometry(5000, 5000);
        const planeMaterial = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
        const dragPlane = new THREE.Mesh(planeGeometry, planeMaterial);
        dragPlane.rotation.x = -Math.PI / 2;

        // Fetch Warehouse Data
        await rpc('/3Dstock/warehouse', { 'company_id': user.context.allowed_company_ids[0] })
            .then(res => { wh_data = res; });
        
        if (!wh_data || wh_data.length === 0) {
            console.error("No warehouse found!");
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
        closeDiv.onclick = () => window.location.reload();

        // 3. Legend (Color box)
        var colorDiv = document.createElement("div");
        colorDiv.classList.add("rectangle");
        const addLegend = (cls, txt) => {
            let d = document.createElement("div"); d.className = cls; colorDiv.appendChild(d);
            let t = document.createElement("div"); t.className = "squareText" + cls.replace(/\D/g,''); 
            if(cls === 'square4') t.className = "squareText4";
            t.innerText = txt; colorDiv.appendChild(t);
        };
        addLegend("square1", "Overload");
        addLegend("square2", "Almost Full");
        addLegend("square3", "Free Space");
        addLegend("square4", "No Product/Load");

        // 4. Sidebar (Drag Source)
        const sidebarDiv = document.createElement("div");
        sidebarDiv.classList.add("location-sidebar");
        sidebarDiv.innerHTML = "<h5 style='text-align:center; padding-bottom:5px; border-bottom:1px solid #ccc;'>Chưa Setup</h5>";
        const sidebarList = document.createElement("div");
        sidebarList.style.maxHeight = "70vh"; sidebarList.style.overflowY = "auto";
        sidebarDiv.appendChild(sidebarList);

        // 5. SELECTION PANEL (Bảng thông tin bên phải)
        const panelDiv = document.createElement("div");
        panelDiv.classList.add("selection-panel");
        panelDiv.innerHTML = `
            <h5>
                <span id="panel_loc_name">Location Name</span>
                <button class="btn-close-panel" id="btn_close_panel">&times;</button>
            </h5>
            
            <div class="info-section">
                <div style="font-size:13px; color:#555;">Trạng thái: <b id="panel_status">...</b></div>
                <button class="btn btn-info btn-sm" id="btn_view_products">
                    <i class="fa fa-cubes"></i> Xem Tồn Kho
                </button>
            </div>

            <div class="edit-section">
                <div class="input-group">
                    <label>Dài (m)</label>
                    <input type="number" id="inp_l" step="0.1">
                </div>
                <div class="input-group">
                    <label>Rộng (m)</label>
                    <input type="number" id="inp_w" step="0.1">
                </div>
                <div class="input-group">
                    <label>Cao (m)</label>
                    <input type="number" id="inp_h" step="0.1">
                </div>
                <div class="input-group">
                    <label>Capacity</label>
                    <input type="number" id="inp_cap">
                </div>
            </div>
            
            <div class="actions">
                <button class="btn btn-primary btn-sm w-100" id="btn_save_changes">
                    <i class="fa fa-save"></i> Lưu Thay Đổi
                </button>
            </div>
            <div style="font-size:10px; color:#999; margin-top:5px; text-align:center;">
                * Kéo mũi tên 3D để sửa vị trí
            </div>
        `;

        start();

        async function start() {
            // Fetch Data
            await rpc('/3Dstock/data', { 
                'company_id': user.context.allowed_company_ids[0], 
                'wh_id': wh_id 
            }).then(res => { data = res; });

            sidebarList.innerHTML = ""; // Reset sidebar

            // Scene Setup
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xdfdfdf);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 6000);
            camera.position.set(0, 400, 600);

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
            content.append(sidebarDiv);
            content.append(panelDiv); // Thêm Panel vào DOM

            // Events
            document.querySelector(".customselect")?.addEventListener("change", warehouseChange);
            document.querySelector("#btn_close_panel").addEventListener("click", deselectObject);
            
            // Logic nút "Lưu Thay Đổi" (Kích thước)
            document.querySelector("#btn_save_changes").addEventListener("click", async () => {
                if (!selectedObject) return;
                const locId = selectedObject.userData.loc_id;
                
                const l = parseFloat(document.getElementById('inp_l').value);
                const w = parseFloat(document.getElementById('inp_w').value);
                const h = parseFloat(document.getElementById('inp_h').value);
                const cap = parseInt(document.getElementById('inp_cap').value);

                // Lưu vào Odoo
                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location',
                    method: 'write',
                    args: [[locId], {
                        'length': l, 'width': w, 'height': h, 'max_capacity': cap
                    }],
                    kwargs: {},
                });
                
                // Vẽ lại khối 3D với kích thước mới mà không cần reload
                updateMeshDimensions(selectedObject, l, w, h);
                // alert("Đã lưu thông tin!"); // Optional
            });

            // Logic nút "Xem Tồn Kho"
            document.querySelector("#btn_view_products").addEventListener("click", async () => {
                if (!selectedObject) return;
                const products = await rpc('/3Dstock/data/product', { 'loc_code': selectedObject.name });
                // --- SỬA LỖI: self.dialog giờ đã tồn tại nhờ hàm setup() ---
                self.dialog.add(CustomDialog, { data: products });
            });

            // Controls
            controls = new THREE.OrbitControls(camera, renderer.domElement);
            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            
            // Khi đang kéo (Drag), tắt xoay camera
            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value;
                if (!event.value && transformControl.object) {
                    saveLocationPosition(transformControl.object); // Lưu vị trí khi thả tay
                }
            });
            scene.add(transformControl);

            // Environment
            const baseGeo = new THREE.BoxGeometry(2000, 0, 2000);
            const baseMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.BackSide });
            scene.add(new THREE.Mesh(baseGeo, baseMat));
            scene.add(dragPlane);

            group = new THREE.Group();

            // Render Objects
            for (let [key, value] of Object.entries(data)) {
                // value: [x, y, z, l, w, h, id]
                const hasPos = (value[0] !== 0 || value[1] !== 0 || value[2] !== 0);
                
                if (hasPos) {
                    await create3DBox(key, value);
                } else {
                    createSidebarItem(key, value);
                }
            }
            scene.add(group);
            raycaster = new THREE.Raycaster();
            animate();

            // Drag & Drop Listeners
            const canvas = renderer.domElement;
            canvas.addEventListener("dragover", (e) => e.preventDefault());
            canvas.addEventListener("drop", onDropLocation);
            
            // CLICK LISTENER (One-Click Selection)
            canvas.addEventListener('click', onCanvasClick);
        }

        // --- XỬ LÝ CLICK CHUỘT ---
        async function onCanvasClick(event) {
            // Nếu đang kéo vật bằng TransformControls thì không tính là click chọn
            if (transformControl.dragging) return;

            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            
            raycaster.setFromCamera(pointer, camera);
            
            // Bắn tia vào các khối hộp
            const intersects = raycaster.intersectObjects(group.children, true); 

            if (intersects.length > 0) {
                // Tìm object chính (Mesh)
                let target = intersects.find(r => r.object.type === 'Mesh' && r.object.userData.loc_id);
                
                if (target) {
                    selectObject(target.object);
                }
            } else {
                // Click ra ngoài -> Bỏ chọn
                // Chỉ bỏ chọn nếu không click vào transform gizmo (mũi tên điều hướng)
                const gizmoIntersects = raycaster.intersectObjects(transformControl.children, true);
                if (gizmoIntersects.length === 0) {
                    deselectObject();
                }
            }
        }

        // --- HÀM CHỌN ĐỐI TƯỢNG ---
        async function selectObject(mesh) {
            if (selectedObject === mesh) return; 
            
            selectedObject = mesh;
            
            // 1. Gắn điều hướng
            transformControl.attach(mesh);
            
            // 2. Hiện Panel
            panelDiv.style.display = "block";
            
            // 3. Điền thông tin vào Panel
            document.getElementById("panel_loc_name").innerText = mesh.name;
            
            let statusText = "Trống";
            if (mesh.userData.color === 0xcc0000) statusText = "Quá tải";
            else if (mesh.userData.color === 0xe6b800) statusText = "Sắp đầy";
            else if (mesh.userData.color === 0x00802b) statusText = "Còn trống";
            document.getElementById("panel_status").innerText = statusText;
            document.getElementById("panel_status").style.color = '#' + mesh.userData.color.toString(16);

            // 4. Lấy dữ liệu chi tiết
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
        }

        function deselectObject() {
            selectedObject = null;
            transformControl.detach();
            panelDiv.style.display = "none";
        }

        // --- CÁC HÀM PHỤ TRỢ ---

        function createSidebarItem(code, val) {
            const item = document.createElement("div");
            item.classList.add("location-item");
            item.innerText = code;
            item.draggable = true;
            item.addEventListener("dragstart", (e) => {
                const dragData = JSON.stringify({
                    id: val[6], code: code,
                    l: val[3] > 0 ? val[3] : 50, 
                    w: val[4] > 0 ? val[4] : 50,
                    h: val[5] > 0 ? val[5] : 50
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
                // Vẽ ngay
                const newData = [point.x, 0, point.z, itemData.l, itemData.w, itemData.h, itemData.id];
                const newMesh = await create3DBox(itemData.code, newData);
                
                // Xóa khỏi sidebar
                Array.from(sidebarList.children).forEach(child => {
                    if (child.innerText === itemData.code) sidebarList.removeChild(child);
                });

                // Lưu DB
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

                // Tự động chọn object vừa thả xuống
                selectObject(newMesh);
            }
        }

        async function create3DBox(key, value) {
            const l = value[3] > 0 ? value[3] : 50;
            const w = value[4] > 0 ? value[4] : 50;
            const h = value[5] > 0 ? value[5] : 50;
            
            const geo = new THREE.BoxGeometry(l, h, w);
            geo.translate(0, h/2, 0); // Pivot ở đáy
            
            const edges = new THREE.EdgesGeometry(geo);
            
            // Lấy màu
            let col = 0x8c8c8c; let op = 0.5;
            await rpc('/3Dstock/data/quantity', { 'loc_code': key }).then(q => {
                if (q[0] > 0) {
                   if (q[1] > 100) col = 0xcc0000;
                   else if (q[1] > 50) col = 0xe6b800;
                   else col = 0x00802b;
                   op = 0.8;
                } else if(q[1] == -1) { col = 0x00802b; op = 0.8; }
            });

            const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: op }));
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
            
            mesh.position.set(value[0], value[1], value[2]);
            line.position.copy(mesh.position);
            
            mesh.name = key;
            mesh.userData = { color: col, loc_id: value[6] };
            
            mesh.add(line); 
            line.position.set(0,0,0);
            
            // Text Label
            const loader = new THREE.FontLoader();
            loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                let tSize = (l > w ? w : l) / 2.5;
                const tGeo = new THREE.ShapeGeometry(font.generateShapes(key, tSize));
                tGeo.translate(0, h/2 + 2, 0);
                const text = new THREE.Mesh(tGeo, textMat);
                
                if (w > l) { 
                     text.rotation.y = Math.PI / 2;
                     text.position.z = l/2 + tSize; 
                } else {
                     text.position.x = -w/2 - tSize;
                }
                mesh.add(text); 
            });

            group.add(mesh);
            return mesh;
        }

        // Hàm cập nhật kích thước Mesh sau khi sửa số
        function updateMeshDimensions(mesh, l, w, h) {
            // Convert Mét -> Pixel (3.779 * 2)
            const pxL = l * 3.779 * 2;
            const pxW = w * 3.779 * 2;
            const pxH = h * 3.779 * 2;
            
            const newGeo = new THREE.BoxGeometry(pxL, pxH, pxW);
            newGeo.translate(0, pxH/2, 0);
            mesh.geometry.dispose();
            mesh.geometry = newGeo;
            
            const line = mesh.children.find(c => c.type === 'LineSegments');
            if(line) {
                line.geometry.dispose();
                line.geometry = new THREE.EdgesGeometry(newGeo);
            }
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
            var selectedBox = document.querySelector(".customselect");
            wh_id = selectedBox.value;
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