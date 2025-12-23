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

export class CustomDialog extends Component {
    static components = { Dialog };
    static template = 'stock_3d_custom_view.ViewLocationData';

    get getData() {
        return this.props.data;
    }
}

export class Stock3DController extends ListController {
    super() {
        super.setup();
    }

    async open3DView(ev) {
        var self = this;
        await ensureJQuery();
        var wh_data;
        var data;
        var loc_quant;
        let controls, renderer, clock, scene, camera, pointer, raycaster;
        // Biến cho TransformControls
        let transformControl;
        var mesh, group;
        var material;
        var loc_color;
        var loc_opacity = 0.5;
        var textSize;
        let selectedObject = null;
        var dialogs = null;
        var wh_id;

        /**
         * Make a jsonRpc call to fetch available warehouses and list it in the dropdown.
         */
        await rpc('/3Dstock/warehouse', {
            'company_id': user.context.allowed_company_ids[0],
        }).then(function(incoming_data) {
            wh_data = incoming_data;
        });
        wh_id = wh_data[0][0];

        // --- UI ELEMENTS ---
        var select = document.createElement("select");
        select.name = "mySelect";
        for (let i = 0; i < wh_data.length; i++) {
            var option = document.createElement("option");
            option.value = wh_data[i][0];
            option.text = wh_data[i][1];
            select.appendChild(option);
            select.classList.add("customselect");
        }

        var closeDiv = document.createElement("button");
        closeDiv.classList.add("closeBtn");
        closeDiv.innerHTML = "&times;";
        // Style cho nút thoát để đảm bảo nổi lên trên
        closeDiv.style.zIndex = "1001"; 
        closeDiv.style.cursor = "pointer";

        var colorDiv = document.createElement("div");
        colorDiv.classList.add("rectangle");
        
        // ... (Giữ nguyên phần tạo Legend màu sắc) ...
        var color1 = document.createElement("div"); color1.classList.add("square1"); colorDiv.appendChild(color1);
        var colorText1 = document.createElement("div"); colorText1.classList.add("squareText1"); colorText1.innerHTML = "Overload"; colorDiv.appendChild(colorText1);
        var color2 = document.createElement("div"); color2.classList.add("square2"); colorDiv.appendChild(color2);
        var colorText2 = document.createElement("div"); colorText2.classList.add("squareText2"); colorText2.innerHTML = "Almost Full"; colorDiv.appendChild(colorText2);
        var color3 = document.createElement("div"); color3.classList.add("square3"); colorDiv.appendChild(color3);
        var colorText3 = document.createElement("div"); colorText3.classList.add("squareText3"); colorText3.innerHTML = "Free Space Available"; colorDiv.appendChild(colorText3);
        var color4 = document.createElement("div"); color4.classList.add("square4"); colorDiv.appendChild(color4);
        var colorText4 = document.createElement("div"); colorText4.classList.add("squareText4"); colorText4.innerHTML = "No Product/Load"; colorDiv.appendChild(colorText4);

        start();

        async function start() {
            await rpc('/3Dstock/data', {
                'company_id': user.context.allowed_company_ids[0],
                'wh_id': wh_id,
            }).then(function(incoming_data) {
                data = incoming_data;
            });

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xdfdfdf);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 6000);
            camera.position.set(0, 400, 600); // Nâng camera lên chút

            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight / 1.164);
            renderer.setPixelRatio(window.devicePixelRatio);
            
            // Render vào DOM
            $(self.rootRef.el).find('.o_list_renderer').addClass('d-none');
            // Xóa canvas cũ nếu có để tránh trùng lặp khi reload warehouse
            $(self.rootRef.el).find('canvas').remove();
            
            var content = $(self.rootRef.el).find('.o_content');
            content.append(renderer.domElement);
            content.append(select);
            content.append(colorDiv);
            content.append(closeDiv);

            var dropdown = document.querySelector(".customselect");
            if (dropdown) dropdown.addEventListener("change", warehouseChange);
            
            var closeBtn = document.querySelector(".closeBtn");
            if (closeBtn) closeBtn.addEventListener("click", onWindowClose);

            // Orbit Controls
            controls = new THREE.OrbitControls(camera, renderer.domElement);

            // --- TRANSFORM CONTROLS (KÉO THẢ) ---
            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value; // Tắt xoay camera khi đang kéo vật
                
                // Khi thả chuột (kết thúc kéo), lưu dữ liệu
                if (!event.value && transformControl.object) {
                    saveLocationPosition(transformControl.object);
                }
            });
            scene.add(transformControl);

            // Base Floor
            const baseGeometry = new THREE.BoxGeometry(800, 0, 800);
            const baseMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.BackSide });
            const baseCube = new THREE.Mesh(baseGeometry, baseMaterial);
            scene.add(baseCube);

            group = new THREE.Group();

            for (let [key, value] of Object.entries(data)) {
                if ((value[0] > 0) || (value[1] > 0) || (value[2] > 0) || (value[3] > 0) || (value[4] > 0) || (value[5] > 0)) {
                    // Tạo Geometry
                    const geometry = new THREE.BoxGeometry(value[3], value[5], value[4]);
                    // Dời tâm vật thể xuống đáy để khớp với tọa độ Odoo (y=0 là mặt sàn)
                    geometry.translate(0, (value[5] / 2), 0);
                    
                    const edges = new THREE.EdgesGeometry(geometry);
                    
                    await rpc('/3Dstock/data/quantity', { 'loc_code': key }).then(function(quant_data) {
                        loc_quant = quant_data;
                    });

                    // Logic màu sắc
                    if (loc_quant[0] > 0) {
                        if (loc_quant[1] > 100) { loc_color = 0xcc0000; loc_opacity = 0.8; }
                        else if (loc_quant[1] > 50) { loc_color = 0xe6b800; loc_opacity = 0.8; }
                        else { loc_color = 0x00802b; loc_opacity = 0.8; }
                    } else {
                        if (loc_quant[1] == -1) { loc_color = 0x00802b; loc_opacity = 0.8; }
                        else { loc_color = 0x8c8c8c; loc_opacity = 0.5; }
                    }

                    material = new THREE.MeshBasicMaterial({ color: loc_color, transparent: true, opacity: loc_opacity });
                    mesh = new THREE.Mesh(geometry, material);
                    
                    const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
                    
                    // Đặt vị trí
                    mesh.position.set(value[0], value[1], value[2]);
                    line.position.set(value[0], value[1], value[2]);

                    // Thêm Text
                    const loader = new THREE.FontLoader();
                    loader.load('https://threejs.org/examples/fonts/droid/droid_sans_bold.typeface.json', function(font) {
                        const textMat = new THREE.MeshBasicMaterial({ color: 0x000000, side: THREE.DoubleSide });
                        if (value[3] > value[4]) textSize = (value[4] / 2) - (value[4] / 2.9);
                        else textSize = (value[3] / 2) - (value[3] / 2.9);
                        
                        const textshapes = font.generateShapes(key, textSize);
                        const textgeometry = new THREE.ShapeGeometry(textshapes);
                        textgeometry.translate(0, ((value[5] / 2) - (textSize / (textSize - 1.5))), 0);
                        
                        const text = new THREE.Mesh(textgeometry, textMat);
                        if (value[4] > value[3]) {
                            text.rotation.y = Math.PI / 2;
                            text.position.set(value[0], value[1], value[2] + (textSize * 2) + ((value[3]/3.779/2)/2) + (textSize/2));
                        } else {
                            text.position.set(value[0] - (textSize * 2) - ((value[4]/3.779/2)/2) - (textSize/2), value[1], value[2]);
                        }
                        scene.add(text);
                    });

                    scene.add(mesh);
                    scene.add(line);
                    
                    mesh.name = key;
                    mesh.userData = {
                        color: loc_color,
                        loc_id: value[6] // ID quan trọng để lưu
                    };
                    group.add(mesh);
                }
            }
            scene.add(group);
            raycaster = new THREE.Raycaster();
            pointer = new THREE.Vector3();
            animate();
        }

        // --- HÀM LƯU TỌA ĐỘ VỀ SERVER ---
        async function saveLocationPosition(obj) {
            if (!obj.userData.loc_id) return;
            
            // Vì geometry đã translate origin xuống đáy, nên obj.position chính là vị trí mặt sàn.
            // Ta lưu trực tiếp x, y, z.
            await rpc('/web/dataset/call_kw', {
                model: 'stock.location',
                method: 'write',
                args: [[obj.userData.loc_id], {
                    'pos_x': obj.position.x,
                    'pos_y': obj.position.y, 
                    'pos_z': obj.position.z,
                }],
                kwargs: {},
            });
            console.log("Updated Position for ID:", obj.userData.loc_id);
        }

        function warehouseChange() {
            var selectedBox = document.querySelector(".customselect");
            wh_id = selectedBox.value;
            start();
        }

        function onWindowResize() {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight / 1.164);
        }

        function onWindowClose() {
            window.location.reload();
        }

        function animate() {
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }

        // --- XỬ LÝ CLICK ---
        // Sử dụng dblclick để chọn vật thể và bật chế độ Edit (Kéo thả)
        window.addEventListener('dblclick', function(event) {
            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            
            raycaster.setFromCamera(pointer, camera);
            const intersects = raycaster.intersectObject(group, true);

            if (intersects.length > 0) {
                const object = intersects[0].object;
                if (object.userData.loc_id) {
                    transformControl.attach(object);
                }
            } else {
                transformControl.detach();
            }
        });

        // Giữ lại sự kiện 'dblclick' cũ của bạn nhưng chuyển thành logic hiển thị Dialog (hoặc dùng click đơn)
        // Để tránh xung đột, tôi gộp logic click để xem info vào đây luôn
        // Lưu ý: Code gốc của bạn dùng 'dblclick' cho info. Giờ ta dùng dblclick cho Edit.
        // Ta có thể dùng Single Click cho Info dialog.
        window.addEventListener('click', async function(event) {
            if (dialogs) return; // Nếu đang mở dialog thì thôi
            
            pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
            pointer.y = -(event.clientY / (window.innerHeight)) * 2 + 1 + 0.13;
            raycaster.setFromCamera(pointer, camera);
            
            // Chỉ bắt sự kiện nếu KHÔNG đang kéo thả
            if (!transformControl.dragging) {
                const intersects = raycaster.intersectObject(group, true);
                if (intersects.length > 0) {
                    const res = intersects[0];
                    // Nếu click vào vật thể và chưa chọn edit
                    if (res.object && transformControl.object !== res.object) {
                        var products;
                        await rpc('/3Dstock/data/product', { 'loc_code': res.object.name }).then(function(pd) {
                            products = pd;
                        });
                        
                        selectedObject = res.object;
                        // selectedObject.material.color.set(0x00ffcc); // Highlight tạm

                        const closeDialog = () => {
                             if(selectedObject) {
                                // selectedObject.material.color.set(selectedObject.userData.color);
                                selectedObject = null;
                             }
                             self.model.dialog.closeAll();
                             dialogs = null;
                        };

                        dialogs = self.model.dialog.add(CustomDialog, { data: products });
                        // Click ra ngoài để đóng logic xử lý trong Dialog component hoặc listener khác
                    }
                }
            }
        });
    }
}

registry.category("views").add("3d_button_in_stock", {
    ...listView,
    Controller: Stock3DController,
    buttonTemplate: 'stock_3d_custom_view.ListView.Buttons'
});