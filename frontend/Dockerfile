FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host makes Vite listen on 0.0.0.0 so Docker port mapping works
CMD ["npm", "run", "dev", "--", "--host"]
