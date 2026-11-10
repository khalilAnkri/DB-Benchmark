SELECT sum(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= toDate('1994-01-01') AND l_shipdate < toDate('1995-01-01')
  AND l_discount BETWEEN toDecimal32('0.05', 2) AND toDecimal32('0.07', 2)
  AND l_quantity < 24;
