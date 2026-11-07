"""Persistent local simulation for Life Behind Glass."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from functools import lru_cache
import json
from math import dist
import random
import secrets
import threading
import time

from cubedesk.background import atomic_json


HOMES = {'lighthouse': 'Дом у маяка', 'coast': 'Дом на побережье', 'forest': 'Дом у леса'}
LOOKS = {'wanderer': 'Путник', 'cat': 'Котик', 'fox': 'Лисёнок'}
COLORS = {'mint': '#79dbbf', 'amber': '#ffc879', 'rose': '#eb9aa9', 'sky': '#8dbbf3'}
SEASONS = ('Весна', 'Лето', 'Осень', 'Зима')
DAY = 1440
MINUTES_PER_SECOND = 4
SEASON_DAYS = 7
HUB = 'square'
PLACES = {'lighthouse': (76, 55), 'coast': (44, 102), 'forest': (169, 61),
          HUB: (114, 104), 'pier': (74, 149), 'grove': (180, 103), 'garden': (143, 131),
          'market': (106, 71), 'workshop': (133, 36), 'inn': (202, 61),
          'west_lane': (29, 43), 'east_lane': (224, 32)}
PLACE_NAMES = {'lighthouse': 'У маяка', 'coast': 'На берегу', 'forest': 'У леса', HUB: 'На площади',
               'pier': 'У причала', 'grove': 'В роще', 'garden': 'У грядок', 'market': 'У лавки',
               'workshop': 'В мастерской', 'inn': 'У трактира', 'west_lane': 'Дома', 'east_lane': 'Дома'}
ROADS = ((HUB, 'market'), (HUB, 'forest'), (HUB, 'grove'), (HUB, 'garden'), (HUB, 'coast'),
         (HUB, 'pier'), ('coast', 'pier'), ('coast', 'west_lane'), ('west_lane', 'lighthouse'),
         ('market', 'lighthouse'), ('market', 'workshop'), ('workshop', 'forest'), ('forest', 'inn'),
         ('inn', 'grove'), ('inn', 'east_lane'))
ROAD_BENDS = {('market','workshop'): ((126,73), (151,58), (149,37)),
              ('inn','east_lane'): ((242,63), (242,36))}
TASKS = {'arrive': 'Обживается', 'sleep': 'Спит', 'breakfast': 'Готовит завтрак',
         'plant': 'Сажает семена', 'tend': 'Ухаживает за грядками', 'harvest': 'Собирает урожай',
         'fish': 'Ловит рыбу', 'gather': 'Собирает ветки',
         'visit': 'Идёт к соседям', 'talk': 'Разговаривает', 'trade': 'Обменивается товарами',
         'walk': 'Гуляет', 'build': 'Мастерит у дома', 'repair': 'Чинит общий причал',
         'event': 'Заметил что-то необычное'}


@dataclass(frozen=True)
class Resident:
    name: str
    role: str
    look: str
    color: str
    home: str
    stops: tuple[tuple[int, str, str], ...]
    shelter: str
    dialogue: tuple[tuple[str, str], ...]


PEOPLE = {
    'mila': Resident('Мила', 'Лавочница', 'wanderer', '#d489a5', 'west_lane',
                     ((470, 'market', 'Открывает лавку'), (700, HUB, 'Идёт за обедом'),
                      (760, 'market', 'Работает в лавке'), (1060, 'inn', 'Ужинает')), 'market',
                     (('Доброе утро!', 'Как дела?'), ('Семена свежие.', 'Зайду ещё.'), ('Что растёт?', 'Уже всходит!'))),
    'lev': Resident('Лев', 'Рыбак', 'wanderer', '#6c99bd', 'west_lane',
                    ((430, 'pier', 'Рыбачит'), (730, 'market', 'Относит улов'),
                     (810, 'coast', 'Чинит сети'), (1080, 'inn', 'Зашёл на ужин')), 'inn',
                    (('Есть клёв!', 'Пойду гляну.'), ('Смотри, улов.', 'Вот это рыба!'), ('Ветер с моря.', 'Слышу волны.'))),
    'nika': Resident('Ника', 'Плотница', 'fox', '#b492c9', 'east_lane',
                     ((490, 'workshop', 'Работает с деревом'), (750, 'grove', 'Выбирает доски'),
                      (870, 'workshop', 'Мастерит'), (1090, HUB, 'Гуляет по площади')), 'workshop',
                     (('Есть доски?', 'Посмотрю дома.'), ('Хороший дуб.', 'На полки?'), ('Нужен молоток?', 'Спасибо, есть.'))),
    'sava': Resident('Савва', 'Смотритель маяка', 'wanderer', '#c8925d', 'west_lane',
                     ((450, 'lighthouse', 'Проверяет маяк'), (690, 'market', 'Заходит в лавку'),
                      (830, 'pier', 'Гуляет у моря'), (1050, 'lighthouse', 'Зажигает маяк')), 'lighthouse',
                     (('Море тихое.', 'И правда.'), ('Маяк в порядке.', 'Вижу его свет.'), ('Знаешь бухту?', 'Расскажи!'))),
    'taya': Resident('Тая', 'Садовница', 'cat', '#dbb86d', 'east_lane',
                     ((475, 'garden', 'Ухаживает за растениями'), (725, 'market', 'Приносит цветы'),
                      (860, 'forest', 'Гуляет у леса'), (1110, 'inn', 'Пьёт чай')), 'inn',
                     (('Есть ростки!', 'Красивые!'), ('Пахнет мятой.', 'Срежем веточку?'), ('Земля сухая.', 'Принесу воды.'))),
    'rina': Resident('Рина', 'Хозяйка трактира', 'wanderer', '#82a687', 'east_lane',
                     ((490, 'market', 'Покупает продукты'), (660, 'inn', 'Готовит обед'),
                      (910, HUB, 'Гуляет'), (990, 'inn', 'Встречает гостей')), 'inn',
                     (('Чай готов.', 'Спасибо, Рина.'), ('Суп с грибами.', 'Как вкусно!'), ('Добрый вечер!', 'И тебе!'))),
}


def road_points(origin, target):
    bends = ROAD_BENDS.get((origin,target), ROAD_BENDS.get((target,origin), ())[::-1])
    return PLACES[origin], *bends, PLACES[target]


@lru_cache(maxsize=180)
def route(origin, target):
    paths = [(0., (origin,))]
    visited = set()
    while paths:
        length, path = min(paths)
        paths.remove((length, path))
        current = path[-1]
        if current == target:
            points = [PLACES[origin]]
            for a,b in zip(path,path[1:]):
                points.extend(road_points(a,b)[1:])
            return tuple(points), length
        if current in visited:
            continue
        visited.add(current)
        for a, b in ROADS:
            other = b if current == a else a if current == b else None
            if other is not None and other not in visited:
                points = road_points(current,other)
                paths.append((length + sum(dist(a,b) for a,b in zip(points,points[1:])), (*path, other)))
    raise ValueError('Место не связано с дорогами посёлка')


def travel_minutes(origin, target):
    return round(route(origin, target)[1] / 2.3)


@dataclass(frozen=True)
class Story:
    place: str
    title: str
    text: str
    seasons: tuple[int, ...] = (0, 1, 2, 3)
    night: bool = False


STORIES = {
    'glow': Story('pier', 'Море зажглось', 'В тёмной воде появились светящиеся следы.', (1, 2), True),
    'deer': Story('grove', 'Олень на тропе', 'Олень вышел из леса и задержался у тропинки.', (0, 1, 2)),
    'letter': Story(HUB, 'Письмо без адреса', 'На площади нашли письмо с рисунком посёлка.', (0, 1, 2, 3)),
    'festival': Story(HUB, 'Фонарики над посёлком', 'Соседи собрались на площади и зажгли фонарики.', (0, 1, 2, 3), True),
    'boat': Story('pier', 'Лодка вернулась', 'В гавани снова появилась лодка, которую давно ждали.'),
    'kite': Story('coast', 'Бумажный змей', 'Ветер сорвал змея с крыши, и он поднялся над берегом.', (0, 1, 2)),
    'tracks': Story('forest', 'Следы на снегу', 'За ночь у лесного дома появились незнакомые следы.', (3,)),
    'lantern': Story('pier', 'Находка после шторма', 'К берегу прибило старый фонарь. Смотритель узнал его по царапине.'),
    'guest': Story('lighthouse', 'Смотритель встретил друга', 'Хозяин фонаря вернулся в посёлок. Теперь фонарь снова горит у маяка.'),
}


def profile_from(data):
    if not isinstance(data, dict):
        raise ValueError('Некорректные данные героя')
    name = data.get('name')
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 24 or not name.isprintable():
        raise ValueError('Введите имя героя длиной до 24 символов')
    profile = {'name': name}
    for key, choices in [('home', HOMES), ('look', LOOKS), ('color', COLORS)]:
        value = data.get(key)
        if not isinstance(value, str) or value not in choices:
            raise ValueError('Выберите дом, внешность и цвет одежды')
        profile[key] = value
    return profile


def calendar(minute):
    index = int(minute) // DAY
    hour, minutes = divmod(int(minute) % DAY, 60)
    season = index // SEASON_DAYS % len(SEASONS)
    return {'day': index + 1, 'season': season, 'time': f'{hour:02}:{minutes:02}', 'hour': hour}


def sky_weather(seed, minute, season):
    roll = random.Random(seed + int(minute) // 360 * 37).random()
    if season == 3:
        return 'snow' if roll < .44 else 'clear'
    return 'rain' if roll < (.19 if season == 1 else .32) else 'clear'


@dataclass
class Move:
    task: str
    origin: str
    target: str
    began: int
    arrival: int
    ends: int

    def position(self, minute):
        if self.origin == self.target or minute >= self.arrival:
            return PLACES[self.target]
        points, length = route(self.origin, self.target)
        remaining = max(0, (minute - self.began) / max(1, self.arrival - self.began)) * length
        for a, b in zip(points, points[1:]):
            leg = dist(a, b)
            if remaining <= leg:
                return tuple(x + (y-x)*remaining/leg for x, y in zip(a, b))
            remaining -= leg
        return points[-1]

    def facing(self, minute):
        x,y = self.position(minute)
        xx,yy = self.position(minute + 1)
        dx,dy = xx-x, yy-y
        if not (dx or dy):
            return 'down'
        return ('right' if dx > 0 else 'left') if abs(dx) > abs(dy) else ('down' if dy > 0 else 'up')


@lru_cache(maxsize=96)
def timetable(seed, day, key):
    person = PEOPLE[key]
    dawn = (day - 1)*DAY + 450
    season = calendar(dawn)['season']
    weather = sky_weather(seed, dawn, season)
    if day % 7 == 6:
        stops = (person.stops[0], (775, HUB, 'На рыночной площади'), (1030, 'inn', 'На общем ужине'))
    elif weather != 'clear':
        stops = ((525, person.shelter, 'Занимается делами под крышей'), (970, 'inn', 'Греется в трактире'))
    else:
        stops = person.stops
    return ((0, person.home, 'Дома'), *stops, (1240, person.home, 'Возвращается домой'))


def resident_move(seed, key, minute):
    day, clock = divmod(int(minute), DAY)
    stops = timetable(seed, day+1, key)
    index = max(index for index, (start, _, _) in enumerate(stops) if start <= clock)
    began, target, job = stops[index]
    origin = stops[max(0, index-1)][1]
    start = day*DAY + began
    end = day*DAY + (stops[index+1][0] if index+1 < len(stops) else DAY)
    return Move(job, origin, target, start, start+travel_minutes(origin,target), end)


@dataclass
class World:
    seed: int
    profile: dict
    move: Move
    minute: int = 360
    wood: int = 0
    garden: int = 0
    harvests: int = 0
    friends: int = 0
    improvements: int = 0
    next_story: int = 360 + 1800
    story_no: int = 0
    active: dict | None = None
    journal: list = field(default_factory=list)
    chain_at: int = 0
    lantern_restored: bool = False
    relationships: dict = field(default_factory=dict)
    recent_chats: list = field(default_factory=list)
    appointment: str | None = None
    conversation: dict | None = None
    produce: int = 0
    fish: int = 0
    coins: int = 0
    pier_repairs: int = 0
    shop_food: int = 0
    pantry: int = 0
    meals: int = 0

    def _set_task(self, task, target, duration):
        origin = self.move.target
        travel = travel_minutes(origin, target)
        self.move = Move(task, origin, target, self.minute, self.minute + travel, self.minute + travel + duration)

    def _visit_options(self):
        if self.minute % DAY >= 1180:
            return []
        last = {entry['resident']: entry['minute'] for entry in reversed(self.recent_chats)}
        visits = []
        for key in PEOPLE:
            stop = resident_move(self.seed, key, self.minute)
            arrival = self.minute + travel_minutes(self.move.target, stop.target)
            if stop.target.endswith('_lane') or not stop.arrival <= arrival <= stop.ends-38:
                continue
            trade = key == 'mila' and stop.target == 'market' and self.produce + self.fish > 0
            if trade or self.minute - last.get(key, -DAY) >= 330:
                score = 3.4 if trade else 2.05 + (.6 if not self.relationships.get(key) else 0)
                visits.append(('visit', stop.target, 34, score, key))
        return visits

    def _start_conversation(self):
        key = self.appointment
        self.appointment = None
        if key not in PEOPLE:
            return
        stop = resident_move(self.seed, key, self.minute)
        if stop.target != self.move.target or not stop.arrival <= self.minute <= stop.ends-32:
            return
        person = PEOPLE[key]
        trade = key == 'mila' and stop.target == 'market' and self.produce + self.fish > 0
        affinity = self.relationships.get(key, 0)
        if trade:
            lines = ('Беру урожай!' if self.produce else 'Беру рыбу!', 'Договорились!')
        elif affinity == 0:
            lines = (f'Я {person.name}.', 'Очень приятно!')
        elif affinity == 4:
            lines = ('Ты уже свой.', 'Мне тут уютно.')
        elif sky_weather(self.seed, self.minute, calendar(self.minute)['season']) == 'rain' and affinity % 3 == 0:
            lines = ('Ливень опять.', 'Переждём тут.')
        else:
            lines = person.dialogue[(affinity - 1) % len(person.dialogue)]
        self.move.task = 'trade' if trade else 'talk'
        self.move.ends = self.minute + 32
        self.conversation = {'resident': key, 'minute': self.minute, 'day': calendar(self.minute)['day'],
                             'lines': list(lines), 'trade': trade}

    def _finish_conversation(self):
        chat = self.conversation
        if not chat:
            return
        key = chat['resident']
        self.relationships[key] = min(30, self.relationships.get(key, 0) + 1)
        self.friends = min(30, self.friends+1)
        if chat['trade']:
            self.coins += 3*self.produce + 2*self.fish
            self.shop_food = min(30, self.shop_food+self.produce+self.fish)
            self.produce = self.fish = 0
        self.recent_chats.insert(0, chat)
        del self.recent_chats[12:]
        self.conversation = None

    def _finish_task(self):
        if self.move.task == 'gather':
            self.wood += 1
        elif self.move.task == 'plant':
            self.garden = 2
        elif self.move.task == 'tend':
            self.garden = min(self.garden + 3, 18)
        elif self.move.task == 'harvest':
            self.garden = 0
            self.harvests += 1
            self.produce = min(30, self.produce + 3)
        elif self.move.task == 'fish':
            self.fish = min(30, self.fish + 1)
        elif self.move.task in ('talk','trade'):
            self._finish_conversation()
        elif self.move.task == 'build':
            self.wood -= 2
            self.coins = max(0, self.coins-3)
            self.improvements += 1
        elif self.move.task == 'repair':
            self.wood -= 2
            self.coins -= 6
            self.pier_repairs += 1

    def _routine(self):
        current = calendar(self.minute)
        home = self.profile['home']
        if current['hour'] >= 22 or current['hour'] < 6:
            self._set_task('sleep', home, (360 - self.minute % DAY) % DAY)
            return
        if current['hour'] < 8 and self.move.task != 'breakfast':
            self._set_task('breakfast', home, max(25, 470 - self.minute % DAY))
            return

        weather = sky_weather(self.seed, self.minute, current['season'])
        rng = random.Random(self.seed + self.minute * 3)
        garden_task = 'plant' if not self.garden else 'harvest' if self.garden >= 12 else 'tend'
        garden_score = 2.1 if garden_task in ('plant','harvest') else 1.6
        if weather != 'clear' or current['season'] == 3:
            garden_score -= 1.3
        options = [('gather', 'grove', 60, 1.7 if self.wood < 2 else .3),
                   ('fish', 'pier', 76, 1.2 if weather == 'clear' else .2),
                   (garden_task, 'garden', 65, garden_score),
                   ('visit', HUB, 56, 1.1 + self.friends * .018),
                   ('walk', rng.choice(tuple(HOMES)), 45, .8),
                   ('build', home, 84, 2.3 if self.wood >= 2 and self.coins >= 3 and self.improvements < 6 else -10),
                   ('repair', 'pier', 90, 2.2 if self.wood >= 2 and self.coins >= 6 and self.pier_repairs < 3 else -10)]
        candidates = [(*item, None) for item in options] + self._visit_options()
        task, place, duration, _, self.appointment = max(candidates, key=lambda item: item[3] + rng.random()*2 - 2*(item[0] == self.move.task))
        self._set_task(task, place, duration)

    def _start_story(self):
        current = calendar(self.minute)
        if self.chain_at and self.minute >= self.chain_at:
            kind = 'guest'
        else:
            if self.minute < self.next_story:
                return
            night = current['hour'] >= 19 or current['hour'] < 6
            choices = [key for key, story in STORIES.items() if key != 'guest'
                       and current['season'] in story.seasons and story.night == night
                       and (key != 'lantern' or not (self.chain_at or self.lantern_restored))]
            recent = {entry['kind'] for entry in self.journal[:3]}
            pool = [key for key in choices if key not in recent] or choices
            if not pool:
                return
            kind = random.Random(self.seed + self.minute).choice(pool)
        story = STORIES[kind]
        self.story_no += 1
        self._set_task('event', story.place, 168)
        self.active = {'id': self.story_no, 'kind': kind, 'ends': self.move.ends}
        self.next_story = self.move.ends + random.Random(self.seed + self.story_no).randint(2800, 4800)
        self.journal.insert(0, {'id': self.story_no, 'kind': kind, 'scene': self.scene(self.move.arrival + 55)})
        del self.journal[24:]

    def _advance_town(self, previous):
        for key in ('lev', 'taya', 'rina'):
            stop = resident_move(self.seed, key, self.minute)
            if not previous < stop.arrival <= self.minute:
                continue
            if key in ('lev','taya') and stop.target == 'market':
                self.shop_food = min(30, self.shop_food+3)
            elif key == 'rina' and stop.target == 'market':
                bought = min(6, self.shop_food, 20-self.pantry)
                self.shop_food -= bought
                self.pantry += bought
            elif key == 'rina' and stop.target == 'inn' and self.pantry:
                cooked = min(5, self.pantry)
                self.pantry -= cooked
                self.meals = min(20, self.meals+cooked)
        if previous//DAY != self.minute//DAY:
            self.meals = max(0, self.meals-4)

    def advance(self):
        previous = self.minute
        self.minute += MINUTES_PER_SECOND
        self._advance_town(previous)
        if self.move.task == 'visit' and self.appointment and self.minute >= self.move.arrival:
            self._start_conversation()
        if self.minute < self.move.ends:
            return
        self._finish_task()
        if self.active:
            if self.active['kind'] == 'lantern':
                self.chain_at = self.minute + 2*DAY
            elif self.active['kind'] == 'guest':
                self.chain_at = 0
                self.lantern_restored = True
                self.friends = min(30, self.friends + 1)
            self.active = None
        self._start_story()
        if not self.active:
            self._routine()

    def scene(self, minute):
        current = calendar(minute)
        position = self.move.position(minute)
        moving = minute < self.move.arrival and self.move.origin != self.move.target
        residents = []
        for index, (key, person) in enumerate(PEOPLE.items()):
            stop = resident_move(self.seed, key, minute)
            walking = minute < stop.arrival
            if stop.target.endswith('_lane') and not walking:
                continue
            x,y = stop.position(minute)
            x += (-9,8,-8,11,4,-4)[index]
            y += (1,4,-5,-3,8,-10)[index]
            if self.conversation and key == self.conversation['resident']:
                x,y = position[0]+10, position[1]
            residents.append({'id': key, 'position': (x,y), 'look': person.look, 'color': person.color,
                              'moving': walking, 'facing': stop.facing(minute), 'task': stop.task, 'place': stop.target})
        chat = None
        if self.conversation:
            speaker = 0 if minute-self.conversation['minute'] < 16 else 1
            chat = {'resident': self.conversation['resident'],
                    'speaker': self.conversation['resident'] if speaker == 0 else 'hero',
                    'text': self.conversation['lines'][speaker]}
        elif not self.active and 0 <= minute % 156 < 28:
            for place, lines in [('market', ('Есть улов?', 'У лавки.')), ('inn', ('Чай готов.', 'Сяду у окна.'))]:
                pair = [resident for resident in residents if resident['place'] == place and not resident['moving']]
                if len(pair) >= 2:
                    speaker = int(minute % 156 >= 14)
                    chat = {'resident': pair[1-speaker]['id'], 'speaker': pair[speaker]['id'], 'text': lines[speaker]}
                    break
        return current | {'profile': dict(self.profile), 'minute': minute, 'position': position,
                          'moving': moving, 'facing': 'right' if self.conversation else self.move.facing(minute),
                          'task': self.move.task, 'target': self.move.target, 'wood': self.wood,
                          'garden': self.garden, 'friends': self.friends, 'improvements': self.improvements,
                          'weather': sky_weather(self.seed, minute, current['season']),
                          'active': self.active['kind'] if self.active else None, 'lantern': self.lantern_restored,
                          'residents': residents, 'dialogue': chat, 'pier_repairs': self.pier_repairs}


class Village:
    def __init__(self, storage):
        self.path = storage / 'village.json'
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._worker = None
        self._last_tick = time.monotonic()
        self._saved_minute = 0
        self.world = None
        try:
            saved = json.loads(self.path.read_text('utf8'))
            if saved.pop('version', None) != 1:
                return
            saved['profile'] = profile_from(saved['profile'])
            saved['move'] = Move(**saved['move'])
            world = World(**saved)
            if (world.move.origin not in PLACES or world.move.target not in PLACES or world.move.task not in TASKS
                    or not all(type(value) is int and value >= 0 for value in (
                        world.minute, world.seed, world.wood, world.garden, world.harvests, world.friends, world.improvements,
                        world.next_story, world.story_no, world.chain_at, world.move.began, world.move.arrival,
                        world.move.ends, world.produce, world.fish, world.coins, world.pier_repairs,
                        world.shop_food, world.pantry, world.meals))
                    or world.minute < 360 or not 0 <= world.improvements <= 6 or not 0 <= world.pier_repairs <= 3
                    or world.shop_food > 30 or world.pantry > 20 or world.meals > 20
                    or not isinstance(world.journal, list) or len(world.journal) > 24
                    or not isinstance(world.relationships, dict) or not isinstance(world.recent_chats, list)
                    or len(world.recent_chats) > 12 or world.appointment not in (*PEOPLE, None)):
                raise ValueError('Некорректное сохранение посёлка')
            for entry in world.journal:
                self._entry(entry)
            if world.active and (world.active['kind'] not in STORIES or world.active['id'] != world.story_no):
                raise ValueError('Некорректное событие посёлка')
            for key, value in world.relationships.items():
                if key not in PEOPLE or type(value) is not int or not 0 <= value <= 30:
                    raise ValueError('Некорректные отношения жителей')
            for chat in world.recent_chats + ([world.conversation] if world.conversation else []):
                if (chat['resident'] not in PEOPLE or not isinstance(chat['lines'], list) or len(chat['lines']) != 2
                        or not all(isinstance(line, str) and len(line) <= 40 for line in chat['lines'])
                        or type(chat['minute']) is not int or type(chat['day']) is not int or type(chat['trade']) is not bool):
                    raise ValueError('Некорректный диалог')
            self.world = world
            self._saved_minute = world.minute
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass

    def configure(self, data):
        profile = profile_from(data)
        with self.lock:
            if self.world:
                candidate = deepcopy(self.world)
                candidate.profile = profile
            else:
                candidate = World(secrets.randbelow(2**31), profile, Move('arrive', profile['home'], profile['home'], 360, 360, 392))
            self._save(candidate)
            self.world = candidate
            self._last_tick = time.monotonic()
            return self.public()

    def _save(self, world):
        atomic_json(self.path, asdict(world) | {'version': 1})
        self._saved_minute = world.minute

    def start(self):
        self._worker = threading.Thread(target=self._run, daemon=True, name='CubeDesk-village')
        self._worker.start()

    def close(self):
        self._stop.set()
        if self._worker:
            self._worker.join()
        with self.lock:
            if self.world and self.world.minute != self._saved_minute:
                try:
                    self._save(self.world)
                except OSError:
                    pass  # Preserve the previous atomic snapshot if the disk is unavailable.

    def _run(self):
        while not self._stop.wait(1):
            with self.lock:
                world = self.world
                if not world:
                    continue
                active = world.active
                world.advance()
                self._last_tick = time.monotonic()
                if active is not world.active or world.minute - self._saved_minute >= 60:
                    try:
                        self._save(world)
                    except OSError:
                        pass  # The world keeps running and the next tick can retry.

    def scene(self):
        with self.lock:
            if not self.world:
                return None
            fraction = min(1, time.monotonic() - self._last_tick)
            return self.world.scene(self.world.minute + fraction * MINUTES_PER_SECOND)

    def public(self):
        with self.lock:
            if not self.world:
                return None
            world = self.world
            current = calendar(world.minute)
            latest = self._entry(world.journal[0]) if world.journal else None
            people = []
            for key, person in PEOPLE.items():
                move = resident_move(world.seed, key, world.minute)
                activity = 'В пути' if world.minute < move.arrival else move.task
                people.append({'name': person.name, 'role': person.role, 'activity': activity,
                               'place': PLACE_NAMES[move.target], 'affinity': world.relationships.get(key, 0)})
            recent = world.conversation or next(iter(world.recent_chats), None)
            chat = dict(recent, name=PEOPLE[recent['resident']].name) if recent else None
            return current | {'key': str(world.seed), 'profile': dict(world.profile), 'season_name': SEASONS[current['season']],
                              'home_name': HOMES[world.profile['home']], 'task': TASKS[world.move.task],
                              'harvests': world.harvests, 'coins': world.coins, 'people': people, 'conversation': chat,
                              'shop_food': world.shop_food, 'meals': world.meals,
                              'stage': 'Старожил' if current['day'] >= 15 else 'Обжился' if world.improvements else 'Новосёл',
                              'active': world.active['id'] if world.active else None, 'latest': latest}

    @staticmethod
    def _entry(entry):
        story = STORIES[entry['kind']]
        return {'id': entry['id'], 'title': story.title, 'text': story.text, 'day': entry['scene']['day']}

    def journal(self):
        with self.lock:
            return [self._entry(entry) for entry in self.world.journal] if self.world else []

    def journal_scene(self, ident):
        with self.lock:
            for entry in self.world.journal if self.world else ():
                if str(entry['id']) == ident:
                    return deepcopy(entry['scene'])
        raise ValueError('Эпизод не найден в журнале')
