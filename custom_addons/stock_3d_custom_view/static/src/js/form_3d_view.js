import { Component, onWillStart, onMounted, onPatched, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { createElement, append } from "@web/core/utils/xml";
import { Notebook } from "@web/core/notebook/notebook";
import { formView } from "@web/views/form/form_view";
import { FormController } from '@web/views/form/form_controller';
import { useService } from "@web/core/utils/hooks";
import {_t} from "@web/core/l10n/translation";
import { ensureJQuery } from '@web/core/ensure_jquery';
import { rpc } from "@web/core/network/rpc";
import {CustomDialog} from "./listview_3d"

export class Stock3DFormView extends Component {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService('dialog');
        onWillStart(async () => {
            await ensureJQuery()
        })

        onMounted(() => {
            this.Open3DView()
        })
    }

    Open3DView() {
        var self = this;
        var wh_data;
        var data;
        var loc_quant;
        let controls, renderer, clock, scene, camera, pointer, raycaster;
        let transformControl; // Biến kéo thả
        var mesh, group;
        var material;
        var loc_color;
        var loc_opacity = 0.5;
        var textSize;
        let selectedObject = null;
        var dialogs = null;
        var wh_id;
        var location_id = self.props.action.context.loc_id || localStorage.getItem("location_id");
        
        if (self.props.action.context.loc_id != null) {
            localStorage.setItem("location_id", self.props.action.context.loc_id);
            localStorage.setItem("company_id", self.props.action.context.company_id);
        }

        // --- TẠO NÚT THOÁT ---
        var closeBtn = document.createElement("button");
        closeBtn.innerHTML = "Thoát / Trở về";
        closeBtn.classList.add("btn", "btn-secondary");
        closeBtn.style.position = "absolute";
        closeBtn.style.top = "10px";
        closeBtn.style.left = "10px";
        closeBtn.style.zIndex = "1005";
        closeBtn.onclick = function() {
            // Quay lại trang trước (Form View chuẩn của Odoo)
            history.back();
        };

        // --- TẠO BẢNG NHẬP LIỆU (EDIT PANEL) ---
        var editPanel = document.createElement("div");
        editPanel.style.position = "absolute";
        editPanel.style.bottom = "20px";
        editPanel.style.right = "20px";
        editPanel.style.backgroundColor = "rgba(255, 255, 255, 0.9)";
        editPanel.style.padding = "15px";
        editPanel.style.borderRadius = "8px";
        editPanel.style.zIndex = "1005";
        editPanel.style.boxShadow = "0 0 10px rgba(0,0,0,0.2)";
        editPanel.style.display = "none"; // Ẩn mặc định, hiện khi load xong

        editPanel.innerHTML = `
            <h5 style="margin-bottom:10px; color:#666;">Cài đặt Location</h5>
            <div style="margin-bottom:5px;">
                <label style="width:70px;">Dài (m):</label>
                <input type="number" id="inp_length" step="0.1" style="width:80px;">
            </div>
            <div style="margin-bottom:5px;">
                <label style="width:70px;">Rộng (m):</label>
                <input type="number" id="inp_width" step="0.1" style="width:80px;">
            </div>
            <div style="margin-bottom:5px;">
                <label style="width:70px;">Cao (m):</label>
                <input type="number" id="inp_height" step="0.1" style="width:80px;">
            </div>
            <div style="margin-bottom:10px;">
                <label style="width:70px;">Capacity:</label>
                <input type="number" id="inp_capacity" style="width:80px;">
            </div>
            <button id="btn_save_dims" class="btn btn-primary btn-sm" style="width:100%;">Lưu Thông Số</button>
            <div style="margin-top:5px; font-size:11px; color:gray;">* Kéo khối hộp để sửa vị trí</div>
        `;

        // --- LEGEND COLORS ---
        var colorDiv = document.createElement("div");
        colorDiv.classList.add("rectangle");
        // ... (Giữ nguyên logic tạo các ô màu chú thích của bạn) ...
        var color1 = document.createElement("div"); color1.classList.add("square1"); colorDiv.appendChild(color1);
        var colorText1 = document.createElement("div"); colorText1.classList.add("squareText1"); colorText1.innerHTML = "Overload"; colorDiv.appendChild(colorText1);
        var color2 = document.createElement("div"); color2.classList.add("square2"); colorDiv.appendChild(color2);
        var colorText2 = document.createElement("div"); colorText2.classList.add("squareText2"); colorText2.innerHTML = "Almost Full"; colorDiv.appendChild(colorText2);
        var color3 = document.createElement("div"); color3.classList.add("square3"); colorDiv.appendChild(color3);
        var colorText3 = document.createElement("div"); colorText3.classList.add("squareText3"); colorText3.innerHTML = "Free Space Available"; colorDiv.appendChild(colorText3);
        var color4 = document.createElement("div"); color4.classList.add("square4blue"); colorDiv.appendChild(color4);
        var colorText4 = document.createElement("div"); colorText4.classList.add("squareText4"); colorText4.innerHTML = "No Product/Load"; colorDiv.appendChild(colorText4);

        start();

        async function start() {
            await rpc('/3Dstock/data/standalone', {
                'company_id': self.props.action.context.company_id || localStorage.getItem("company_id"),
                'loc_id': self.props.action.context.loc_id || localStorage.getItem("location_id"),
            }).then(function(incoming_data) {
                data = incoming_data;
            });

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xdfdfdf);
            clock = new THREE.Clock();
            camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.5, 6000);
            camera.position.set(0, 200, 300)
            
            renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight / 1.163);
            renderer.setPixelRatio(window.devicePixelRatio);
            
            var o_content = $('.o_content')
            o_content.empty(); // Xóa nội dung cũ để tránh duplicate canvas
            o_content.append(renderer.domElement);
            o_content.append(colorDiv);
            o_content.append(closeBtn); // Thêm nút thoát
            o_content.append(editPanel); // Thêm bảng sửa

            controls = new THREE.OrbitControls(camera, renderer.domElement);
            
            // --- TRANSFORM CONTROLS ---
            transformControl = new THREE.TransformControls(camera, renderer.domElement);
            transformControl.addEventListener('dragging-changed', function (event) {
                controls.enabled = !event.value;
                // Lưu vị trí khi thả chuột
                if (!event.value && selectedObject) {
                    savePosition(selectedObject);
                }
            });
            scene.add(transformControl);

            const baseGeometry = new THREE.BoxGeometry(800, 0, 800);
            const baseMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.FrontSide });
            const baseCube = new THREE.Mesh(baseGeometry, baseMaterial);
            scene.add(baseCube);
            
            group = new THREE.Group();

            for (let [key, value] of Object.entries(data)) {
                if ((value[0] > 0) || (value[1] > 0) || (value[2] > 0) || (value[3] > 0) || (value[4] > 0) || (value[5] > 0)) {
                    const geometry = new THREE.BoxGeometry(value[3], value[5], value[4]);
                    geometry.translate(0, (value[5] / 2), 0);
                    const edges = new THREE.EdgesGeometry(geometry);

                    await rpc('/3Dstock/data/quantity', { 'loc_code': key }).then(function(quant_data) {
                        loc_quant = quant_data;
                    });

                    // Logic màu sắc
                    if (localStorage.getItem("location_id") == value[6]) {
                        // Đây là Location đang được chọn để xem/sửa
                        if (loc_quant[0] > 0) {
                            if (loc_quant[1] > 100) { loc_color = 0xcc0000; loc_opacity = 0.8; } 
                            else if (loc_quant[1] > 50) { loc_color = 0xe6b800; loc_opacity = 0.8; } 
                            else { loc_color = 0x00802b; loc_opacity = 0.8; }
                        } else {
                            if (loc_quant[1] == -1) { loc_color = 0x00802b; loc_opacity = 0.8; } 
                            else { loc_color = 0x0066ff; loc_opacity = 0.8; }
                        }
                    } else {
                        loc_color = 0x8c8c8c; loc_opacity = 0.5;
                    }

                    material = new THREE.MeshBasicMaterial({ color: loc_color, transparent: true, opacity: loc_opacity });
                    mesh = new THREE.Mesh(geometry, material);
                    
                    const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x404040 }));
                    
                    mesh.position.set(value[0], value[1], value[2]);
                    line.position.set(value[0], value[1], value[2]);

                    // ... (Code tạo Text giữ nguyên) ...
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
                        loc_id: value[6],
                    };
                    group.add(mesh);

                    // --- AUTO ATTACH CONTROL ---
                    // Nếu mesh này trùng với ID location đang mở, tự động gắn control và điền form
                    if (value[6] == location_id) {
                        selectedObject = mesh;
                        transformControl.attach(mesh);
                        
                        // Fill dữ liệu vào bảng Edit
                        editPanel.style.display = "block";
                        // Lưu ý: data từ server về có thể đã được nhân với (3.779 * 2)
                        // Nên khi hiển thị lên form để sửa (mét), ta chia ngược lại
                        const conversion = (3.779 * 2);
                        document.getElementById('inp_length').value = (value[3] / conversion).toFixed(2);
                        document.getElementById('inp_width').value = (value[4] / conversion).toFixed(2);
                        document.getElementById('inp_height').value = (value[5] / conversion).toFixed(2);
                        
                        // Lấy capacity hiện tại
                        await rpc('/web/dataset/call_kw', {
                            model: 'stock.location',
                            method: 'read',
                            args: [[parseInt(location_id)], ['max_capacity']],
                            kwargs: {}
                        }).then(res => {
                            if (res && res[0]) document.getElementById('inp_capacity').value = res[0].max_capacity;
                        });
                    }
                }
            }
            scene.add(group);
            raycaster = new THREE.Raycaster();
            pointer = new THREE.Vector3();
            animate();
            
            // --- SỰ KIỆN NÚT LƯU TRÊN FORM ---
            document.getElementById('btn_save_dims').addEventListener('click', async () => {
                if(!location_id) return;
                
                const l = parseFloat(document.getElementById('inp_length').value);
                const w = parseFloat(document.getElementById('inp_width').value);
                const h = parseFloat(document.getElementById('inp_height').value);
                const c = parseInt(document.getElementById('inp_capacity').value);

                await rpc('/web/dataset/call_kw', {
                    model: 'stock.location',
                    method: 'write',
                    args: [[parseInt(location_id)], {
                        'length': l,
                        'width': w,
                        'height': h,
                        'max_capacity': c
                    }],
                    kwargs: {},
                });
                
                // Reload lại để vẽ lại khối hộp theo kích thước mới
                window.location.reload(); 
            });
        }

        async function savePosition(obj) {
            await rpc('/web/dataset/call_kw', {
                model: 'stock.location',
                method: 'write',
                args: [[parseInt(obj.userData.loc_id)], {
                    'pos_x': obj.position.x,
                    'pos_y': obj.position.y,
                    'pos_z': obj.position.z,
                }],
                kwargs: {},
            });
        }

        function onWindowResize() {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight / 1.163);
        }

        function animate() {
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }
    }
}

Stock3DFormView.template = "stock_3d_custom_view.Location3DFormView"
registry.category("actions").add("open_form_3d_view", Stock3DFormView);