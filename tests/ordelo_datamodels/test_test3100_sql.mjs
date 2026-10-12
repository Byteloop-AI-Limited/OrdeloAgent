/** Real PostgreSQL regression checks in an isolated PGlite database.
 * Run: node tests/ordelo_datamodels/test_test3100_sql.mjs /path/to/@electric-sql/pglite/dist/index.js
 * The dependency is kept outside the application; see docs/test-orders.md.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { PGlite } = await import(pathToFileURL(resolve(process.argv[2])).href);
const db = new PGlite();
const sql = (path) => readFile(new URL(`../../${path}`, import.meta.url), 'utf8');
await db.exec(`
CREATE TABLE food_order (
 order_id text PRIMARY KEY, order_number text UNIQUE, seq_id int, recipient text,
 notes text, thread_id text, action text, total_price float8, payment_status text,
 origin_channel text, storefront text, payment_mode text, idempotency_key text UNIQUE);
CREATE TABLE order_item (
 order_id text REFERENCES food_order(order_id), product_name text, sku text,
 quantity int CHECK(quantity>0), price float8, modifications text[]);
CREATE TABLE rider_master (rider_id varchar(12), priority int, town text, vehicle_type text, is_in_shift bool);
CREATE TABLE delivery_dispatch (
 dispatch_id bigserial PRIMARY KEY, order_number text, rider_id varchar(12), rider_payout float8,
 distance float8, vehicle_type text, status text, status_update_dtts timestamp);
CREATE TABLE delivery_inflight (rider_id varchar(12), dispatch_id bigint);
CREATE TABLE delivery_detail (order_number text, rider_payout float8, distance float8, vehicle_type text, status text, town text);
CREATE TABLE delivery_summary (order_number text PRIMARY KEY, status text, redispatch_dtts timestamptz);
CREATE TABLE takeaway_summary (order_number text PRIMARY KEY, status text);
CREATE TABLE ordelo_config (config_key text, config_value text);
CREATE TABLE web_payment_release (order_number text, completed_at timestamptz);
`);
const item = (name, extra={}) => ({ product_name:name, sku:'food', quantity:1, price:3, modifications:['normal modifier'], ...extra });
const order = (id, extra={}) => ({ order_id:id, order_number:`ELAS-${id}`, recipient:'NORMAL', thread_id:'t', action:'delivery', total_price:3, ...extra });
const create = async (id, items, extra={}) => (await db.query(
 'SELECT create_food_order_with_items($1::jsonb,$2::jsonb) AS result', [JSON.stringify(order(id,extra)), JSON.stringify(items)]
)).rows[0].result;
// All executable copies must preserve the same contract, including idempotency.
for (const path of [
 'ordelo_datamodels/jobs_n_functions/create_food_order_with_items.sql',
 'ordelo_datamodels/migrations/ordelo_agg_r1.sql',
 'ordelo_datamodels/migrations/ordelo_agg_r1_test_payment.sql',
 'ordelo_datamodels/migrations/ordelo_agg_r3.sql',
]) {
 const source = await sql(path);
 const definitions = source.match(/CREATE OR REPLACE FUNCTION public\.create_food_order_with_items\(.*?END\s*\$\$;/gs);
 assert.equal(definitions.length, 1, path);
 await db.exec(definitions[0]);
 for (const [name, mode] of [['TEST3100','test'],['Burger','live'],['test3100','live'],[' TEST3100','live'],['TEST3100 ','live'],['TEST3100 Burger','live']]) {
  const id=`copy-${path.split('/').at(-1)}-${name}`;
  const result=await create(id,[item(name)],{payment_mode:mode==='test'?'live':'test',idempotency_key:id});
  assert.equal(result.order.payment_mode,mode);
  assert.equal(result.order.idempotency_key,id);
 }
}
// Installing the new-order rule must leave even NULL-mode old records untouched.
await db.exec("INSERT INTO food_order(order_id,order_number,payment_mode,payment_status) VALUES ('LEGACY-LIVE','ELAS-LEGACY-LIVE','live','requires_capture'),('LEGACY-TEST','ELAS-LEGACY-TEST','test','requires_capture'),('UNRESOLVED','ELAS-UNRESOLVED',NULL,'requires_capture'); INSERT INTO order_item(order_id,product_name,quantity,price) VALUES ('LEGACY-LIVE','TEST3100',1,3),('LEGACY-TEST','Burger',1,10);");
await db.exec(`
CREATE FUNCTION public.assert_test_order_cutover_ready() RETURNS void LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Old historical readiness check must never run'; END; $$;
CREATE FUNCTION public.forbid_payment_environment_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Old global payment-mode trigger must be removed'; END; $$;
CREATE TRIGGER food_order_payment_environment_fixed BEFORE UPDATE OF payment_mode ON food_order
FOR EACH ROW EXECUTE FUNCTION forbid_payment_environment_change();
`);
await db.exec(await sql('ordelo_datamodels/migrations/test3100_order_routing.sql'));
await db.exec(await sql('ordelo_datamodels/migrations/test3100_order_routing.sql')); // Repeatable cleanup/definitions.
await db.exec(await sql('ordelo_datamodels/jobs_n_functions/job_create_dispatch.sql'));
assert.deepEqual((await db.query("SELECT order_id,payment_mode FROM food_order WHERE order_id IN ('LEGACY-LIVE','LEGACY-TEST','UNRESOLVED') ORDER BY order_id")).rows,
 [{order_id:'LEGACY-LIVE',payment_mode:'live'},{order_id:'LEGACY-TEST',payment_mode:'test'},{order_id:'UNRESOLVED',payment_mode:null}]);
assert.deepEqual((await db.query(`SELECT
 to_regprocedure('public.assert_test_order_cutover_ready()') IS NULL AS readiness_removed,
 to_regprocedure('public.forbid_payment_environment_change()') IS NULL AS protection_removed,
 NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='food_order_payment_environment_fixed') AS trigger_removed`)).rows[0],
 {readiness_removed:true,protection_removed:true,trigger_removed:true});
await create('MARKER',[item('Burger',{price:10}),item('TEST3100')]);
await create('NORMAL',[item('Burger',{sku:'TEST3100',modifications:['TEST3100']})],{recipient:'OPS1',payment_mode:'test'});
assert.deepEqual((await db.query("SELECT product_name,price,quantity,modifications FROM order_item WHERE order_id='MARKER' ORDER BY price")).rows,
 [{product_name:'TEST3100',price:3,quantity:1,modifications:['normal modifier']},{product_name:'Burger',price:10,quantity:1,modifications:['normal modifier']}]);
assert.equal((await db.query("SELECT order_has_test_item('ELAS-MARKER') AS marker, order_has_test_item('ELAS-NORMAL') AS normal, order_has_test_item('MISSING') AS missing")).rows[0].marker,true);
assert.deepEqual((await db.query("SELECT order_has_test_item('ELAS-NORMAL') AS normal, order_has_test_item('MISSING') AS missing")).rows[0],{normal:false,missing:null});
await assert.rejects(create('ROLLBACK',[item('TEST3100',{quantity:0})]));
assert.equal((await db.query("SELECT count(*)::int AS n FROM food_order WHERE order_id='ROLLBACK'")).rows[0].n,0);
await db.exec(`
INSERT INTO rider_master VALUES
 ('NORMAL',0,'salisbury','car',true),('OPS1',10,'salisbury','car',true),('OPS2',20,'salisbury','car',true),
 ('OFFSHIFT',1,'salisbury','car',false),('OTHER-TOWN',1,'london','car',true),('OTHER-CAR',1,'salisbury','bike',true),
 ('INFLIGHT',1,'salisbury','car',true);
INSERT INTO delivery_inflight VALUES ('INFLIGHT',999);
INSERT INTO ordelo_config VALUES ('overwatch_list',' OPS1,OPS2, OFFSHIFT,OTHER-TOWN,OTHER-CAR,INFLIGHT '),('DISPATCH_BATCH_SIZE_CAR','1');
INSERT INTO delivery_detail VALUES ('ELAS-MARKER',5,2,'car','unassigned','salisbury'),('ELAS-NORMAL',5,2,'car','unassigned','salisbury');
INSERT INTO delivery_summary VALUES ('ELAS-MARKER','unassigned',NULL),('ELAS-NORMAL','unassigned',NULL);
`);
const candidates = async (n) => (await db.query('SELECT * FROM get_available_riders($1,$2,$3) ORDER BY priority',[n,'salisbury','car'])).rows.map(r=>r.rider_id);
assert.deepEqual(await candidates('ELAS-MARKER'),['OPS1','OPS2']);
assert.deepEqual(await candidates('ELAS-NORMAL'),['NORMAL','OPS1','OPS2']);
assert.deepEqual(await candidates('MISSING'),[]);
await db.query('SELECT job_create_dispatch()');
assert.deepEqual((await db.query('SELECT order_number,rider_id FROM delivery_dispatch ORDER BY order_number')).rows,
 [{order_number:'ELAS-MARKER',rider_id:'OPS1'},{order_number:'ELAS-NORMAL',rider_id:'NORMAL'}]);
// Exercise the actual cancellation function: the next dispatch round stays restricted.
await db.exec(await sql('ordelo_datamodels/jobs_n_functions/dispatch_cancel_before_pickup.sql'));
await db.exec("UPDATE delivery_dispatch SET status='assigned' WHERE order_number='ELAS-MARKER'; UPDATE delivery_summary SET status='assigned' WHERE order_number='ELAS-MARKER'; INSERT INTO delivery_inflight SELECT rider_id,dispatch_id FROM delivery_dispatch WHERE order_number='ELAS-MARKER';");
await db.query("SELECT dispatch_cancel_before_pickup((SELECT dispatch_id FROM delivery_dispatch WHERE order_number='ELAS-MARKER'))");
assert.deepEqual(await candidates('ELAS-MARKER'),['OPS2']);
await db.exec("INSERT INTO delivery_detail VALUES ('ELAS-MARKER',5,2,'car','unassigned','salisbury')");
await db.query('SELECT job_create_dispatch()');
assert.equal((await db.query("SELECT rider_id FROM delivery_dispatch WHERE order_number='ELAS-MARKER' AND status='unassigned'")).rows[0].rider_id,'OPS2');
await db.exec("DELETE FROM ordelo_config WHERE config_key='overwatch_list'");
assert.deepEqual(await candidates('ELAS-MARKER'),[]);
await create('FRESH-NORMAL',[item('Burger')]);
assert.deepEqual(await candidates('ELAS-FRESH-NORMAL'),['NORMAL','OPS1','OPS2']);
console.log('SQL checks passed: four RPC copies, exact marker, retained receipt items, atomic rollback, historical rows untouched, artifact cleanup, rider eligibility/batching and actual redispatch.');
await db.close();
