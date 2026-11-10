DROP DATABASE IF EXISTS d;
DROP DATABASE IF EXISTS b;
CREATE DATABASE b;
CREATE TABLE b.lineitem (
  l_orderkey Int32, l_partkey Int32, l_suppkey Int32, l_linenumber Int32,
  l_quantity Decimal(15,2), l_extendedprice Decimal(15,2),
  l_discount Decimal(15,2), l_tax Decimal(15,2),
  l_returnflag String, l_linestatus String,
  l_shipdate Date, l_commitdate Date, l_receiptdate Date,
  l_shipinstruct String, l_shipmode String, l_comment String
) ENGINE = MergeTree ORDER BY (l_orderkey, l_linenumber);
CREATE TABLE b.orders (
  o_orderkey Int32, o_custkey Int32, o_orderstatus String, o_totalprice Decimal(15,2),
  o_orderdate Date, o_orderpriority String, o_clerk String, o_shippriority Int32,
  o_comment String
) ENGINE = MergeTree ORDER BY o_orderkey;
CREATE TABLE b.part (
  p_partkey Int32, p_name String, p_mfgr String, p_brand String, p_type String,
  p_size Int32, p_container String, p_retailprice Decimal(15,2), p_comment String
) ENGINE = MergeTree ORDER BY p_partkey;
