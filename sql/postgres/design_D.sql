CREATE SCHEMA d;
CREATE TABLE d.lineitem AS
  SELECT * FROM b.lineitem ORDER BY l_shipdate, l_orderkey, l_linenumber;
ALTER TABLE d.lineitem ADD PRIMARY KEY (l_orderkey, l_linenumber);
CREATE INDEX lineitem_shipdate_brin ON d.lineitem USING brin (l_shipdate);
VACUUM ANALYZE d.lineitem;
