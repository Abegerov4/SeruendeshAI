import test from 'node:test';
import assert from 'node:assert/strict';
import {astanaToday, addDays, shiftMonth, monthDays, calendarMove, selectCalendarDate, buildEventsQuery, eventPath, safeExternalUrl, relevantSessions, imageOrientation, ongoingEventEndDay} from '../src/events.js';

test('quick dates use the actual Astana day across UTC midnight and month boundaries', () => {
  assert.equal(astanaToday(new Date('2026-10-19T20:00:00Z')), '2026-10-20');
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(addDays('2028-02-28', 1), '2028-02-29');
});

test('calendar is a Monday-first complete grid and month moves preserve the day where possible', () => {
  const days = monthDays('2026-11');
  assert.equal(days.length, 42);
  assert.equal(days[0], '2026-10-26');
  assert.equal(days[6], '2026-11-01');
  assert.equal(shiftMonth('2026-01-31', 1), '2026-02-28');
  assert.equal(calendarMove('2026-11-01', 'Home'), '2026-10-26');
  assert.equal(calendarMove('2026-11-01', 'End'), '2026-11-01');
  assert.equal(calendarMove('2026-11-01', 'ArrowRight'), '2026-11-02');
});

test('range selection is inclusive, handles reverse selection and restarts after a complete range', () => {
  const start = selectCalendarDate({from:'', to:''}, '2026-11-10', 'range');
  assert.deepEqual(start, {from:'2026-11-10', to:''});
  const range = selectCalendarDate(start, '2026-11-07', 'range');
  assert.deepEqual(range, {from:'2026-11-07', to:'2026-11-10'});
  assert.deepEqual(selectCalendarDate(range, '2026-12-01', 'range'), {from:'2026-12-01', to:''});
  assert.deepEqual(selectCalendarDate(start, '2026-11-08', 'day'), {from:'2026-11-08', to:'2026-11-08'});
});

test('list queries preserve independent archive and feed criteria without empty values', () => {
  const query = buildEventsQuery({view:'archive', q:'  музыка ', month:'2026-09', category:'music', source:'sxodim', price:'free', date_from:'', date_to:''}, 20);
  assert.equal(query.get('view'), 'archive');
  assert.equal(query.get('q'), 'музыка');
  assert.equal(query.get('offset'), '20');
  assert.equal(query.get('limit'), '20');
  assert.equal(query.has('date_from'), false);
  assert.equal(query.get('source'), 'sxodim');
});

test('deep links encode event ids and source links reject non-web protocols', () => {
  assert.equal(eventPath('sxodim:123'), '/events/sxodim%3A123');
  assert.equal(safeExternalUrl('javascript:alert(1)'), null);
  assert.equal(safeExternalUrl('//evil.test'), null);
  assert.equal(safeExternalUrl('https://sxodim.com/astana/event/a'), 'https://sxodim.com/astana/event/a');
});


test('series cards use the next session or the session inside selected dates', () => {
  const event = {start:'2026-02-21T19:00:00+05:00',sessions:['2026-10-31T19:00:00+05:00','2026-10-24T19:00:00+05:00','2026-10-26T19:00:00+05:00']};
  assert.deepEqual(relevantSessions(event, {}, '2026-10-20'), ['2026-10-24T19:00:00+05:00','2026-10-26T19:00:00+05:00','2026-10-31T19:00:00+05:00']);
  assert.deepEqual(relevantSessions(event, {from:'2026-10-26',to:'2026-10-26'}, '2026-10-20'), ['2026-10-26T19:00:00+05:00']);
});

test('continuous multi-day events retain their interval instead of treating a start marker as a session', () => {
  const event = {start:'2026-11-02T10:00:00+05:00',end:'2026-11-04T20:00:00+05:00',schedule_kind:'continuous',sessions:['2026-11-02T10:00:00+05:00']};
  assert.deepEqual(relevantSessions(event, {}, '2026-10-20'), []);
  assert.deepEqual(relevantSessions({...event,schedule_kind:undefined}, {}, '2026-10-20'), []);
  assert.deepEqual(relevantSessions({...event,schedule_kind:'sessions'}, {}, '2026-10-20'), ['2026-11-02T10:00:00+05:00']);
});

test('image orientation uses intrinsic dimensions and treats nearly square art consistently', () => {
  for (const [width, height, expected] of [[600,1200,'portrait'],[1200,450,'landscape'],[850,1000,'square'],[1150,1000,'square'],[849,1000,'portrait'],[1151,1000,'landscape']]) {
    assert.equal(imageOrientation(width,height), expected);
  }
});

test('unavailable or invalid image dimensions do not leave an orientation behind', () => {
  for (const [width,height] of [[0,800],[800,0],[-1,800],[Infinity,800],[800,NaN],[undefined,800],['600',800]]) {
    assert.equal(imageOrientation(width,height), 'unknown');
  }
});

test('compact continuous dates begin after the Almaty start day and include their final day', () => {
  const event = {schedule_kind:'continuous',start:'2026-10-19T20:30:00Z',end:'2026-10-21T19:30:00Z'};
  assert.equal(ongoingEventEndDay(event,'2026-10-20'), '');
  assert.equal(ongoingEventEndDay(event,'2026-10-21'), '2026-10-22');
  assert.equal(ongoingEventEndDay(event,'2026-10-22'), '2026-10-22');
  assert.equal(ongoingEventEndDay(event,'2026-10-23'), '');
});

test('compact continuous dates preserve future intervals, sessions, archives and unknown dates', () => {
  const event = {schedule_kind:'continuous',start:'2028-02-28',end:'2028-03-01'};
  assert.equal(ongoingEventEndDay(event,'2028-02-29'), '2028-03-01');
  assert.equal(ongoingEventEndDay(event,'2028-02-27'), '');
  assert.equal(ongoingEventEndDay({...event,schedule_kind:'sessions'},'2028-02-29'), '');
  assert.equal(ongoingEventEndDay({...event,is_archived:true},'2028-02-29'), '');
  assert.equal(ongoingEventEndDay({...event,start:'not-a-date'},'2028-02-29'), '');
  assert.equal(ongoingEventEndDay({...event,end:null},'2028-02-29'), '');
});
