  value,
  sub,
  tone,
}: {
  icon: any;
  label: string;
  value: any;
  sub: string;
  tone: string;
}) {
  return (
    <div className="metric">
      <div className="metricTop">
        <span>{label}</span>
        <i className={tone}>{icon}</i>
      </div>
      <b>{value}</b>
      <small>{sub}</small>
    </div>
  );
}

function DataTable({
  title,
  subtitle,
  rows,
  cols,
}: {
  title: string;
  subtitle: string;
  rows: any[];
  cols: string[];
}) {
  return (
    <div className="panel tablePanel">
      <div className="panelHead">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>
      <div className="tableScroll">
        <table>
          <thead>
            <tr>
              {cols.map((column) => (
                <th key={column}>{column.replaceAll('_', ' ').toUpperCase()}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {cols.map((column) => (
                  <td key={column}>
                    {column.includes('url') && row[column] ? (
                      <a href={row[column]} target="_blank" rel="noreferrer">
                        Quelle ↗
                      </a>
                    ) : (
                      String(row[column] ?? '—')
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <div className="empty">
            Noch keine importierten Datensätze. CSV-Dateien unter data/imports ergänzen.
          </div>
        )}
      </div>
    </div>
  );
}

function Calc() {
  const [capital, setCapital] = useState(4500);
  const [risk, setRisk] = useState(0.5);
  const [entry, setEntry] = useState(100);
  const [stop, setStop] = useState(95);

  const loss = entry > stop && entry > 0 ? ((entry - stop) / entry) * 100 : 0;
  const maxRisk = (capital * risk) / 100;
  const amount = loss > 0 ? maxRisk / (loss / 100) : 0;

  return (
    <div className="calc">
      {[
        ['Trading capital (€)', capital, setCapital],
        ['Risk per trade (%)', risk, setRisk],
        ['Entry (€)', entry, setEntry],
        ['Stop (€)', stop, setStop],
      ].map(([label, value, setter]: any) => (
        <label key={label}>
          {label}
          <input
            type="number"
            min="0"
            step="any"
            value={value}
            onChange={(event) => setter(Number(event.target.value))}
          />
        </label>
      ))}
      <div className="calcResult">
        <span>Position size</span>
        <b>{Math.floor(amount).toLocaleString('de-DE')} €</b>
        <small>
          Max. Risiko: {maxRisk.toFixed(2)} € · Stop-Abstand: {loss.toFixed(2)}%
        </small>
        {entry <= stop && (
          <small className="failedText">Der Einstieg muss über dem Stop-Kurs liegen.</small>
        )}
      </div>
    </div>
  );
}
