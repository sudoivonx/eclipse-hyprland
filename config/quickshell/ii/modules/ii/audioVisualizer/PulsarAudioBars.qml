import QtQuick
Canvas {
 id: root
 property var levels: []
 property color activeColor: "#80CBC4"
 property string style: "bars-box"
 property bool vertical: false
 property bool reverse: false
 onLevelsChanged: requestPaint()
 onActiveColorChanged: requestPaint()
 onStyleChanged: requestPaint()
 onVerticalChanged: requestPaint()
 onReverseChanged: requestPaint()
 onWidthChanged: requestPaint()
 onHeightChanged: requestPaint()
 function v(i){const level=Math.max(0,Math.min(1,Number(levels[i%levels.length])||0));return Math.max(0.04,level)}
 onPaint:{
  const c=getContext("2d"),w=width,h=height,n=levels.length;
  c.clearRect(0,0,w,h);if(!n||w<1||h<1)return;
  const radial=style.endsWith("-circle"),mode=style.replace("-box","").replace("-circle","");
  const cx=w/2,cy=h/2,r=Math.min(w,h)*.18,R=Math.min(w,h)*.47;
  const L=vertical?h:w,T=vertical?w:h,step=L/n,gap=Math.min(3,step*.22),col=x=>Qt.lighter(activeColor,1+x*.8);
  c.lineCap="round";c.lineJoin="round";
  if(radial){
   if(mode==="wave"||mode==="spine"){
    c.beginPath();for(let i=0;i<=n;i++){let a=-Math.PI/2+i*2*Math.PI/n,xv=v(i),rr=mode==="wave"?r+xv*(R-r):r+xv*(R-r)*.32,x=cx+Math.cos(a)*rr,y=cy+Math.sin(a)*rr;i?c.lineTo(x,y):c.moveTo(x,y)}
    c.strokeStyle=activeColor;c.lineWidth=mode==="spine"?5:2.5;c.stroke();
    if(mode==="spine")for(let i=0;i<n;i++){let a=-Math.PI/2+i*2*Math.PI/n,rr=r+v(i)*(R-r)*.32;c.beginPath();c.arc(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr,3,0,7);c.fillStyle=col(v(i));c.fill()}return;
   }
   if(mode==="particles"){for(let i=0;i<n;i++){let a=-Math.PI/2+i*2*Math.PI/n,rr=r+v(i)*(R-r);c.beginPath();c.arc(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr,2+v(i)*4,0,7);c.fillStyle=col(v(i));c.fill()}return}
   if(mode==="levels"){for(let i=0;i<n;i++){let a=-Math.PI/2+i*2*Math.PI/n;c.beginPath();c.arc(cx,cy,r,a,a+2*Math.PI/n*.8);c.strokeStyle=col(v(i));c.lineWidth=Math.max(2,(R-r)*v(i));c.stroke()}return}
   for(let i=0;i<n;i++){let a=-Math.PI/2+i*2*Math.PI/n,xv=v(i),inner=mode==="splitter"?r+(R-r)*.45:r,outer=inner+(R-inner)*xv;c.beginPath();c.moveTo(cx+Math.cos(a)*inner,cy+Math.sin(a)*inner);c.lineTo(cx+Math.cos(a)*outer,cy+Math.sin(a)*outer);c.strokeStyle=col(xv);c.lineWidth=Math.max(2,Math.PI*2*r/n*.6);c.stroke()}return;
  }
  if(mode==="wave"||mode==="spine"){
   c.beginPath();for(let i=0;i<n;i++){let xv=v(reverse?n-1-i:i),p=(i+.5)*step,off=(xv-.5)*T*.86,x=vertical?T/2+off:p,y=vertical?p:(mode==="spine"?T/2-off:T-xv*T*.9);if(mode==="wave"&&vertical)x=reverse?T-xv*T*.9:xv*T*.9;i?c.lineTo(x,y):c.moveTo(x,y)}
   c.strokeStyle=activeColor;c.lineWidth=mode==="spine"?5:2.5;c.stroke();
   if(mode==="spine")for(let i=0;i<n;i++){let xv=v(reverse?n-1-i:i),p=(i+.5)*step,off=(xv-.5)*T*.86;c.beginPath();c.arc(vertical?T/2+off:p,vertical?p:T/2-off,3,0,7);c.fillStyle=col(xv);c.fill()}return;
  }
  if(mode==="particles"){for(let i=0;i<n;i++){let xv=v(reverse?n-1-i:i),p=(i+.5)*step,off=(i%2?-1:1)*(.12+xv*.32)*T;c.beginPath();c.arc(vertical?(reverse?T-off:off):p,vertical?p:T/2-off,2+xv*4,0,7);c.fillStyle=col(xv);c.fill()}return}
  for(let i=0;i<n;i++){
   let xv=v(reverse?n-1-i:i),p=i*step+gap/2,b=Math.max(1,step-gap);c.fillStyle=col(xv);
   if(mode==="levels"){let a=Math.max(1,T*xv*.48);if(vertical)c.fillRect(T/2-a,p,a*2,b);else{c.fillRect(p,T/2-a,b,a);c.fillRect(p,T/2,b,a)}}
   else if(mode==="splitter"){let count=Math.max(2,Math.floor(T/8)),on=Math.ceil(xv*count),seg=T/count;for(let j=0;j<on;j++){if(vertical)c.fillRect(j*seg,p,seg*.68,b);else c.fillRect(p,T-(j+1)*seg,b,seg*.68)}}
   else if(mode==="bars"){let a=Math.max(1,T*xv);if(vertical)c.fillRect(reverse?T-a:0,p,a,b);else c.fillRect(p,T-a,b,a)}
  }
 }
}
