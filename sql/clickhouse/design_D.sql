CREATE DATABASE d;
CREATE TABLE d.lineitem AS b.lineitem
  ENGINE = MergeTree ORDER BY (l_shipdate, l_orderkey, l_linenumber);
INSERT INTO d.lineitem SELECT * FROM b.lineitem;
CREATE TABLE d.orders AS b.orders;
INSERT INTO d.orders SELECT * FROM b.orders;
CREATE TABLE d.part AS b.part;
INSERT INTO d.part SELECT * FROM b.part;
OPTIMIZE TABLE d.lineitem FINAL;
OPTIMIZE TABLE d.orders FINAL;
OPTIMIZE TABLE d.part FINAL;
