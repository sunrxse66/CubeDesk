"""Shared tile map, solid objects and collision-aware navigation for all actors."""
from dataclasses import dataclass
from functools import lru_cache
import heapq
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = (640,512)
CELL = 4
RESOURCE = Path(__file__).with_name('resources')/'village'


@dataclass(frozen=True)
class MapObject:
    ident: str
    name: str
    kind: str
    bounds: tuple
    solid: tuple | None
    asset: str

    @property
    def depth(self):
        return self.solid[3] if self.solid else self.bounds[3]



class GameMap:
    def __init__(self):
        data=json.loads((RESOURCE/'world.json').read_text('utf8'))
        self.revision=data['revision']
        self.tiles=tuple(data['tiles'])
        self.tile_size=data['tile_size']
        if tuple(data['size']) != SIZE or any(len(row)*self.tile_size != SIZE[0] for row in self.tiles):
            raise ValueError('Invalid village tile grid')
        self.garden=tuple(data['garden'])
        self.objects=tuple(MapObject(item['id'],item['name'],item['kind'],tuple(item['bounds']),
                                    tuple(item['solid']) if item['solid'] else None,item['asset'])
                           for item in data['objects'])
        self.collision=Image.new('L',SIZE)
        self.water=Image.new('L',SIZE)
        self.roads=Image.new('L',SIZE)
        cd=ImageDraw.Draw(self.collision);wd=ImageDraw.Draw(self.water);rd=ImageDraw.Draw(self.roads)
        for y,row in enumerate(self.tiles):
            for x,char in enumerate(row):
                box=(x*self.tile_size,y*self.tile_size,(x+1)*self.tile_size-1,(y+1)*self.tile_size-1)
                if char in 'WR':wd.rectangle(box,fill=255)
                else:cd.rectangle(box,fill=255)
                if char in 'PCBD':rd.rectangle(box,fill=255)
        for obj in self.objects:
            if obj.solid:
                left,top,right,bottom=obj.solid
                cd.rectangle((left-2,top-2,right+2,bottom+2),fill=0)
        self.width,self.height=SIZE[0]//CELL,SIZE[1]//CELL
        self.walkable=tuple(self.collision.getpixel((x*CELL+2,y*CELL+2))!=0
                            for y in range(self.height) for x in range(self.width))
        self.costs=tuple(1 if self.roads.getpixel((x*CELL+2,y*CELL+2)) else 2.4
                         for y in range(self.height) for x in range(self.width))
        self.points={key:self.nearest(tuple(point)) for key,point in data['points'].items()}

    def nearest(self,point):
        cx,cy=point[0]//CELL,point[1]//CELL
        candidates=[]
        for y in range(max(0,cy-4),min(self.height,cy+5)):
            for x in range(max(0,cx-4),min(self.width,cx+5)):
                if self.walkable[y*self.width+x]:
                    p=(x*CELL+2,y*CELL+2)
                    candidates.append((math.dist(p,point),p))
        if not candidates:
            raise ValueError('РЈ РјРµСЃС‚Р° РЅР°Р·РЅР°С‡РµРЅРёСЏ РЅРµС‚ СЃРІРѕР±РѕРґРЅРѕРіРѕ РІС…РѕРґР°')
        return min(candidates)[1]

    @lru_cache(maxsize=512)
    def path(self,origin,target):
        start=self.points[origin];end=self.points[target]
        source=(start[0]//CELL,start[1]//CELL);goal=(end[0]//CELL,end[1]//CELL)
        queue=[(0.,0.,source)]
        scores={source:0.};parents={}
        while queue:
            _,cost,current=heapq.heappop(queue)
            if cost>scores[current]:
                continue
            if current==goal:
                cells=[current]
                while current in parents:
                    current=parents[current];cells.append(current)
                points=tuple((x*CELL+2,y*CELL+2) for x,y in reversed(cells))
                return points,sum(math.dist(a,b) for a,b in zip(points,points[1:]))
            x,y=current
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx,ny=x+dx,y+dy
                if not (0<=nx<self.width and 0<=ny<self.height and self.walkable[ny*self.width+nx]):
                    continue
                if dx and dy and not (self.walkable[y*self.width+nx] and self.walkable[ny*self.width+x]):
                    continue
                score=cost+math.hypot(dx,dy)*self.costs[ny*self.width+nx]
                neighbor=(nx,ny)
                if score<scores.get(neighbor,float('inf')):
                    scores[neighbor]=score;parents[neighbor]=current
                    heapq.heappush(queue,(score+math.dist(neighbor,goal),score,neighbor))
        raise ValueError(f'РќРµС‚ СЃРІРѕР±РѕРґРЅРѕРіРѕ РїСѓС‚Рё РјРµР¶РґСѓ {origin} Рё {target}')


@lru_cache(maxsize=1)
def game_map():
    return GameMap()
