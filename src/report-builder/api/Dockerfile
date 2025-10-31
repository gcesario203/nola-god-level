# build
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY report-builder.csproj ./
RUN dotnet restore
COPY . .
RUN dotnet publish -c Release -o /out

# runtime
FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app
COPY --from=build /out .
EXPOSE 8080
ENTRYPOINT ["dotnet", "report-builder.dll"]