"""Two low-resolution, black-and-white GIF charts from committed observations."""
from PIL import Image,ImageDraw,ImageFont
import math,datetime

def draw_chart(path,series,xticks,ymax,axis=None,ymin=0):
 W,H=288,144;L,R,T,B=29,281,15,119
 im=Image.new('1',(W,H),1);d=ImageDraw.Draw(im);font=ImageFont.load_default_imagefont();coords=[]
 labels=[f'{ymin+(ymax-ymin)*k/4:g}' for k in range(5)]
 L=max(L,max(d.textbbox((0,0),label,font=font)[2] for label in labels)+4)
 def txt(x,y,s,anchor='left'):
  box=d.textbbox((0,0),s,font=font);width=box[2]-box[0]
  if anchor=='right':x-=width
  elif anchor=='middle':x-=width//2
  d.text((x,y),s,font=font,fill=0)
 for v in [ymin+(ymax-ymin)*k/4 for k in range(5)]:
  yy=round(B-(v-ymin)*(B-T)/(ymax-ymin));d.line((L-2,yy,R,yy),fill=0,width=1) if v==0 else d.line((L-2,yy,L,yy),fill=0)
  txt(L-4,yy-5,f'{v:g}','right')
 d.line((L,T,L,B),fill=0);txt(L,1,'%')
 n=len(series[0][0]);positions=axis['positions'] if axis else list(range(n));lo,hi=axis['domain'] if axis else (0,max(1,n-1))
 x=lambda k:round(L+(k-lo)*(R-L)/(hi-lo));y=lambda v:round(B-(v-ymin)*(B-T)/(ymax-ymin))
 for k,t in xticks:txt(x(k),127,t,'right' if (axis and k==0) or (not axis and k==n-1) else 'middle')
 if axis:
  rx=x(0)
  for yy in range(T,B,8):d.line((rx,yy,rx,min(yy+3,B-1)),fill=0)
  txt(rx,1,'GDP release','right')
 for values,dashed in series:
  pts=[(x(k),y(v)) for k,v in zip(positions,values)];coords.append(pts)
  if len(pts)==1:d.point(pts[0],fill=0)
  for a,b in zip(pts,pts[1:]):
   if dashed:
    distance=math.dist(a,b)
    for pos in range(0,math.ceil(distance),6):
     u=pos/distance;v=min(pos+3,distance)/distance
     d.line((round(a[0]+u*(b[0]-a[0])),round(a[1]+u*(b[1]-a[1])),round(a[0]+v*(b[0]-a[0])),round(a[1]+v*(b[1]-a[1]))),fill=0)
   else:d.line((a,b),fill=0)
 im.convert('RGB').quantize(colors=2,dither=Image.Dither.NONE).save(path,format='GIF',optimize=True)
 return {'size':[W,H],'series_pixels':coords,'ymax':ymax,'ymin':ymin,'plot_bounds':[L,T,R,B],**({'date_axis':axis,'release_line_x':x(0)} if axis else {})}


def build_charts(out,latest,errors):
 """Render observed points only, using the live chart's release-date precedence."""
 geometry={}
 h=next((h for h in latest.get('horizons',[]) if h['kind']=='nowcast'),None)
 if latest.get('status')=='ok' and h:
  vintages=sorted((v for v in latest.get('vintages',[]) if v['target_quarter']==h['quarter']),key=lambda v:v['run_date'])
  release_date=h.get('release_date') or latest.get('next_gdp_release_date')
  if vintages and release_date:
   release=datetime.date.fromisoformat(release_date)
   days=[(datetime.date.fromisoformat(v['run_date'])-release).days for v in vintages]
   axis={'positions':days,'domain':[math.floor(min(-95,*days)/5)*5,max(5,*days)],'release_date':release_date,'last_observed_date':vintages[-1]['run_date']}
   ticks=[(days[j],f"{datetime.date.fromisoformat(vintages[j]['run_date']).day} {datetime.date.fromisoformat(vintages[j]['run_date']):%b}") for j in range(0,len(vintages),4) if days[j]<=-18]+[(0,f'{release.day} {release:%b}')]
   series=[([v[k] for v in vintages],k!='qoq_growth_pct') for k in ['qoq_growth_pct','ci_68_low','ci_68_high']]
   values=[v for points,_ in series for v in points]
   geometry['nowcast.gif']=draw_chart(out/'nowcast.gif',series,ticks,max(1,math.ceil(max(values)*4)/4),axis,min(0,math.floor(min(values)*4)/4))
   geometry['nowcast.gif']['source_points']=vintages
 if errors:
  series=[([r[k] for r in errors],k=='qoq_nowcast_pct') for k in ['qoq_actual_pct','qoq_nowcast_pct']]
  # Four readable ticks across whatever length of track record is available.
  indexes=sorted(set(round(k*(len(errors)-1)/3) for k in range(4)))
  ticks=[(j,' '.join(reversed(errors[j]['target_quarter'].split()))) for j in indexes]
  values=[v for points,_ in series for v in points]
  geometry['record.gif']=draw_chart(out/'record.gif',series,ticks,max(1.2,math.ceil(max(values)*4)/4),None,min(0,math.floor(min(values)*4)/4))
  geometry['record.gif']['source_points']=errors
 return geometry
