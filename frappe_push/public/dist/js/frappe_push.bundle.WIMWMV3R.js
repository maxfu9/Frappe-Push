(()=>{frappe.provide("frappe_push");console.log("Frappe Push script loaded from /assets/frappe_push/js/frappe_push.js");frappe_push.init=function(){if(!window.frappe_push_initialized){if(window.frappe_push_initialized=!0,console.log("Frappe Push initializing for user:",frappe.session.user),console.log("Current Notification Permission:",Notification.permission),!("Notification"in window)){console.log("This browser does not support desktop notification");return}if(Notification.permission==="denied"){console.warn("Frappe Push: Notifications are BLOCKED by the browser. Please reset permissions in the address bar (lock icon).");return}console.log("Frappe Push: Fetching config..."),frappe.call({method:"frappe_push.frappe_push.api.get_public_config",callback:function(o){console.log("Frappe Push: Config API response:",o.message),o.message?frappe_push.setup_firebase(o.message):console.log("Frappe Push: No config received or app disabled.")},error:function(o){console.error("Frappe Push: API Error:",o)}})}};frappe_push.setup_firebase=function(o){frappe.require(["https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js","https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js"],function(){try{firebase.apps.length||firebase.initializeApp(o);let n=firebase.messaging();navigator.serviceWorker.register("/api/method/frappe_push.frappe_push.api.get_service_worker",{scope:"/"}).then(p=>(console.log("Frappe Push: Service Worker registered with scope:",p.scope),navigator.serviceWorker.ready)).then(p=>new Promise(h=>setTimeout(()=>h(p),1e3))).then(p=>{function h(e=!1){e||frappe.show_alert({message:__("Requesting permission..."),indicator:"blue"});let i=c=>{c==="granted"?(e||frappe.show_alert({message:__("Permission granted! Finalizing..."),indicator:"green"}),n.getToken({vapidKey:o.vapidKey,serviceWorkerRegistration:p}).then(t=>{t?(console.log("Frappe Push: Token retrieved successfully!"),frappe_push.register_token(t),localStorage.setItem("frappe_push_subscribed","true"),e||frappe.show_alert({message:__("Successfully subscribed!"),indicator:"green"})):e||frappe.show_alert({message:__("No token available."),indicator:"orange"})}).catch(t=>{console.error("An error occurred while retrieving token. ",t),e||frappe.msgprint(__("Failed to get Push Token: ")+t.message)})):(console.log("Unable to get permission:",c),e||frappe.show_alert({message:__("Notification permission denied."),indicator:"red"}))},r=Notification.requestPermission();r?r.then(i):Notification.requestPermission(i)}n.onMessage(e=>{console.log("Frappe Push: Foreground message received:",e),e&&m(e)});function m(e){let i=e.data||{},r=e.notification||{},c="push-notify-"+Date.now(),t=r.icon||i.notification_icon||o.siteLogo,a=r.title||i.title||__("New Notification"),l=r.body||i.body||"",s=i.click_action||i.click_action_url||null;if(!a&&!l)return;if(Notification.permission==="granted"){let u=new Notification(a,{body:l,icon:t,tag:i.document_name||"frappe-push-"+Date.now()});u.onclick=f=>{if(f.preventDefault(),window.focus(),s){let g=s;if(s.startsWith(window.location.origin)&&(g=s.replace(window.location.origin,"")),g.startsWith("/app")&&window.frappe){let x=g.replace(/^\/app\//,"");frappe.set_route(x)}else window.location.href=s}u.close()}}let y=document.querySelectorAll(".frappe-push-notification").length*100,w=`
							<div id="${c}" class="frappe-push-notification" style="
								position: fixed;
								bottom: ${20+y}px;
								right: 20px;
								width: calc(100% - 40px);
								max-width: 380px;
								background: rgba(255, 255, 255, 0.98);
								backdrop-filter: blur(12px);
								-webkit-backdrop-filter: blur(12px);
								border-radius: 20px;
								padding: 24px;
								box-shadow: 0 15px 40px rgba(0,0,0,0.12);
								display: flex;
								flex-direction: column;
								gap: 16px;
								z-index: 1000000;
								font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
								cursor: pointer;
								transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease, bottom 0.3s ease;
								transform: translateX(400px);
								opacity: 0;
								border: 1px solid rgba(0,0,0,0.05);
							">
								<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">
									<div style="font-weight: 700; font-size: 16px; color: #1a1a1a;">${a}</div>
									<button class="notify-close" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #bbb; line-height: 1; padding: 0;">&times;</button>
								</div>
								<div style="font-size: 14px; color: #444; line-height: 1.5;">${l}</div>
								${s?`
									<button class="notify-action" style="
										background: #2563eb;
										color: white;
										border: none;
										border-radius: 12px;
										padding: 10px 16px;
										font-weight: 600;
										font-size: 14px;
										cursor: pointer;
										width: fit-content;
										transition: background 0.2s;
									">${__("Open Details")}</button>
								`:""}
							</div>
						`;document.body.insertAdjacentHTML("beforeend",w);let d=document.getElementById(c);setTimeout(()=>{d.style.transform="translateX(0)",d.style.opacity="1"},100);let b=()=>{d.style.transform="translateX(400px)",d.style.opacity="0",setTimeout(()=>{d.remove(),document.querySelectorAll(".frappe-push-notification").forEach((u,f)=>{u.style.bottom=20+f*100+"px"})},400)};d.onclick=u=>{if(u.target.classList.contains("notify-close"))b();else if(s){let f=s;if(s.startsWith(window.location.origin)&&(f=s.replace(window.location.origin,"")),f.startsWith("/app")&&window.frappe){let g=f.replace(/^\/app\//,"");frappe.set_route(g),b()}else window.location.href=s}else b()}}Notification.permission==="default"?_():Notification.permission==="granted"&&h(!0);function _(){if(document.getElementById("frappe-push-banner"))return;let e=frappe.session.user==="Guest",i=e?__("Stay Updated"):__("Direct Alerts"),r=e?__("Get real-time updates on your orders and exclusive offers from Europlast."):__("Receive instant alerts for assignments, mentions, and system notifications."),c=`
							<div id="frappe-push-overlay" style="
								position: fixed;
								top: 0;
								left: 0;
								width: 100%;
								height: 100%;
								background: rgba(0, 0, 0, 0.4);
								backdrop-filter: blur(4px);
								-webkit-backdrop-filter: blur(4px);
								z-index: 999998;
								opacity: 0;
								transition: opacity 0.3s ease;
							"></div>
							<div id="frappe-push-banner" style="
								position: fixed;
								top: 50%;
								left: 50%;
								transform: translate(-50%, -40%);
								width: calc(100% - 40px);
								max-width: 400px;
								background: rgba(255, 255, 255, 0.98);
								border-radius: 20px;
								padding: 24px;
								box-shadow: 0 20px 50px rgba(0,0,0,0.15);
								display: flex;
								flex-direction: column;
								gap: 16px;
								z-index: 999999;
								font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
								opacity: 0;
								transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
							">
								<div style="display: flex; justify-content: space-between; align-items: flex-start;">
									<div style="font-weight: 700; font-size: 18px; color: #1a1a1a;">${i} \u{1F514}</div>
									<button id="push-close" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #bbb; line-height: 1;">&times;</button>
								</div>
								<div style="font-size: 15px; color: #444; line-height: 1.5;">
									${r}
								</div>
								<button id="push-enable" style="
									background: #2563eb;
									color: white;
									border: none;
									border-radius: 12px;
									padding: 12px 20px;
									font-weight: 600;
									font-size: 16px;
									cursor: pointer;
									transition: transform 0.1s, background 0.2s;
								">${__("Enable Notifications")}</button>
							</div>
						`;document.body.insertAdjacentHTML("beforeend",c);let t=document.getElementById("frappe-push-banner"),a=document.getElementById("frappe-push-overlay");setTimeout(()=>{a.style.opacity="1",t.style.transform="translate(-50%, -50%)",t.style.opacity="1"},50),document.getElementById("push-enable").onclick=()=>{h(!1),l()},document.getElementById("push-close").onclick=l,a.onclick=l;function l(){a.style.opacity="0",t.style.transform="translate(-50%, -40%)",t.style.opacity="0",setTimeout(()=>{t.remove(),a.remove()},400)}}}).catch(p=>{console.error("Frappe Push: Service Worker registration failed:",p)})}catch(n){console.error("Firebase Setup Error:",n)}})};frappe_push.register_token=function(o){let n=localStorage.getItem("frappe_push_device_id");n||(n=frappe.utils.get_random(16),localStorage.setItem("frappe_push_device_id",n)),frappe.call({method:"frappe_push.frappe_push.api.subscribe",args:{fcm_token:o,browser:navigator.userAgent,device_id:n}})};console.log("Frappe Push Script Execution Started");$(function(){$(document).one("click",function(){frappe_push.init()})});})();
//# sourceMappingURL=frappe_push.bundle.WIMWMV3R.js.map
