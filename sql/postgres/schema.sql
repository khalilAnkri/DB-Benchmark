DROP SCHEMA IF EXISTS d CASCADE;
DROP SCHEMA IF EXISTS b CASCADE;
CREATE SCHEMA b;
CREATE TABLE b.lineitem (
  l_orderkey INTEGER NOT NULL, l_partkey INTEGER NOT NULL, l_suppkey INTEGER NOT NULL,
  l_linenumber INTEGER NOT NULL,
  l_quantity NUMERIC(15,2), l_extendedprice NUMERIC(15,2),
  l_discount NUMERIC(15,2), l_tax NUMERIC(15,2),
  l_returnflag VARCHAR(1), l_linestatus VARCHAR(1),
  l_shipdate DATE, l_commitdate DATE, l_receiptdate DATE,
  l_shipinstruct VARCHAR(25), l_shipmode VARCHAR(10), l_comment VARCHAR(44));
CREATE TABLE b.orders (
  o_orderkey INTEGER NOT NULL, o_custkey INTEGER NOT NULL, o_orderstatus VARCHAR(1),
  o_totalprice NUMERIC(15,2), o_orderdate DATE, o_orderpriority VARCHAR(15),
  o_clerk VARCHAR(15), o_shippriority INTEGER, o_comment VARCHAR(79));
CREATE TABLE b.part (
  p_partkey INTEGER NOT NULL, p_name VARCHAR(55), p_mfgr VARCHAR(25), p_brand VARCHAR(10),
  p_type VARCHAR(25), p_size INTEGER, p_container VARCHAR(10),
  p_retailprice NUMERIC(15,2), p_comment VARCHAR(23));
