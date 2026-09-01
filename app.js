const tg=window.Telegram?.WebApp;if(tg){tg.ready();tg.expand()}
const user=tg?.initDataUnsafe?.user||{id:0,first_name:"Guest"};
document.getElementById("hello").textContent=`👋 ${user.first_name}`;
document.getElementById("uid").textContent=`ID: ${user.id}`;
async function api(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
function toast(t){const x=document.getElementById("toast");x.textContent=t;x.style.display="block";setTimeout(()=>x.style.display="none",2500)}
async function load(){const c=await fetch("/api/catalog").then(r=>r.json());
document.getElementById("proxyInfo").textContent=`${c.proxy.name} • ${c.proxy.mb} MB • ৳${c.proxy.price} • Stock ${c.proxy_stock}`;
document.getElementById("vpnInfo").textContent=`${c.vpn.name} • ${c.vpn.days} Days • ৳${c.vpn.price} • Stock ${c.vpn_stock}`;
try{const p=await api("/api/profile",{user_id:user.id});document.getElementById("balance").textContent=`৳${Number(p.balance).toFixed(2)}`;
document.getElementById("orders").innerHTML=p.orders.length?p.orders.slice().reverse().map(o=>`<div class="order">#${o.id} • ${o.product.toUpperCase()} • ৳${o.amount}</div>`).join(""):"No orders yet."}catch(e){toast(e.message)}}
async function buy(product){if(!user.id){toast("Telegram Mini App-এর ভিতর থেকে খুলুন");return}if(!confirm("এই item কিনতে চান?"))return;
try{const d=await api("/api/buy",{user_id:user.id,product});toast(`✅ Order #${d.order_id} সফল`);alert(`Delivery:\\n\\n${d.item}`);load()}catch(e){toast(e.message)}}
function showHelp(){alert("Payment ও Support-এর জন্য bot-এর Help section ব্যবহার করুন।")}load();